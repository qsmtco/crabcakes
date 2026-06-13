# PROPOSAL: Activity Bubble UX Overhaul

**Date:** 2026-06-01
**Author:** QTR (Kage-7)
**Status:** ~~Proposal — pending Captain approval~~ **Pending post-toolbar-migration redesign.** References to `ChatControlBar` describe the stubbed label that was replaced by `ChatInputToolbar`. The "add a toggle in `ChatControlBar`" plan needs re-targeting to the new toolbar (or a different UX surface) — see `docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md` for the current toolbar layout.

> **Status (verified 2026-06-12):** ❌ **SUPERSEDED** — Phase 2 (event bubbles for tool calls, plan updates, approvals, command output, file edits) from `PROPOSAL-smarter-chat-ux.md` was abandoned. The production approach is now `ui/views/activity_drawer.py` (32K, 2026-06-07) — a GTK4 drawer panel, not inline chat bubbles. `ActivityBubble` model exists (`models/activity.py`) and `set_on_activity_bubble` callback exists in `activity_handler.py:155`, but the bubble-in-chat approach described here was not built. The activity-drawer is the active implementation.

> **Historical note (2026-06-12):** Predates the `ChatControlBar` → `ChatInputToolbar` migration. The proposed "add toggle in ChatControlBar" step is now obsolete; the toggle would need to be added to `ChatInputToolbar` instead.
**Priority:** High
**Effort:** Tier 1 (6-7 days) for full impact, Tier 2 (1-2 weeks) for polish

---

## Why

### The Problem

The activity bubble system — eight ephemeral pill-shaped indicators showing what agents are doing in real time — is **architecturally sound but UX-broken in three independent dimensions**:

1. **Volume imbalance.** The Coder agent fires 5+ `command_output` bubbles per file touched (read → edit → test → lint → commit). The other 7 types fire far less often. In a typical 10-minute Coder session, the user sees 30+ EXEC pills while `lifecycle_start` appears once. The visual signal-to-noise ratio is bad.

2. **No expiration.** Every bubble ever emitted is appended to the chat container and never removed (`ui/handlers/chat_render_handler.py:589-621`). After a long session, the chat viewport is dominated by 1,400+ pixels of system pills pushing the actual conversation off-screen.

3. **Unconditional auto-scroll.** The renderer has 14 `self._mc.scroll_chat_to_bottom()` call sites (`ui/handlers/chat_handler.py:185, 274, 302, 312, 342, 369, 409, 427, 454, 482, 666, 766` plus more). Every activity bubble render triggers one. There is no awareness of whether the user is reading older content. The chat "runs away" from the user.

### Why It Matters Now

The Captain is actively losing trust in the bubble system. The data is genuinely useful — knowing Coder ran `pytest` and it took 1,247ms is real signal. But the delivery mechanism treats every datum as equally important and equally novel, when most of them are noise that's better collapsed into a summary. **The user is asking to suppress the data because the data is loud. That is the wrong outcome.** The right outcome is to keep the data and quiet the delivery.

The FeedBar (the small status bar at the top of the chat, `ui/views/feedbar.py`) already carries overlapping information with the bubbles — `⚙ exec` in the FeedBar AND `exec  exit 0  1,247ms` as a pill. The two surfaces have not been deliberately divided. The natural evolution is: FeedBar = primary real-time surface, bubbles = secondary on-demand log.

### Why Not Just Remove the Bubbles

The data is valuable. A user who wants to see what Coder is doing should be able to see it. The complaint is not "too much information" — it's "information delivered in a way that interferes with the conversation." Removing bubbles would discard a real signal. The fix is to make the signal opt-in, collapsed, and non-interfering with the chat scroll.

---

## What

This proposal contains **two tiers**: Tier 1 (quick fixes) and Tier 2 (polish). **Tier 3 (sidecar) was removed at Captain's request — the System Chat Bubble Container (Fix 1.4) is the final structural answer.**

### Tier 1 — Quick Fixes (6-7 days, recommended for immediate ship)

Four independent changes that together transform the experience without touching the architecture. **Originally proposed as four (1.1 EXEC-collapse, 1.2 toggle, 1.3 no-scroll, 1.4 container); after Captain feedback, Fix 1.1 became a general counter-collapse for all same-type bubbles (not just EXEC) and is no longer subsumed by Fix 1.4. Fix 1.5 (content enrichment) was added after investigation revealed the gateway doesn't send the command string or agent name — client-side correlation is the only fix path available.**

#### Fix 1.1 — Counter-collapse consecutive same-type bubbles (mutate in place)

**Current:** Each event produces one pill. 5 EXEC commands in a row → 5 stacked pills inside the System Bubble Container. Still scannable but noisy.

**Proposed:** Consecutive bubbles of the **same type** collapse into a **single mutating counter bubble**. The bubble displays:
- A **count badge** (highlighted number) that increments in real time
- The **last command** string (so the user knows what was most recently run)
- The **total duration** summed across all collapsed events

When a different event type arrives (e.g., a `read_file` after 5 EXECs), the counter bubble closes (no new widget added), and a new bubble for the new type starts. The counter is per-type, per-session, per-agent-turn (lifecycle).

**Visual example:**

```
╔══════════════════════════════════════╗
║  System                              ║
║  ┌──────────────────────────────┐   ║
║  │ exec ×5  pytest tests/  4.2s │   ║
║  │ read ×2                      │   ║
║  │ exec ×3  ruff check  1.1s   │   ║
║  └──────────────────────────────┘   ║
╚══════════════════════════════════════╝
```

**Behavior (confirmed with Captain):**

1. **Grouping rule:** Same type only. `pytest` then `ruff` then `pytest` = 3 separate counter bubbles (or 1 with broken continuity? — proposal: 3 separate, simpler and more honest).
2. **Display:** Count + last command + total duration. Example: `exec ×5  pytest tests/test_auth.py  4,247ms`.
3. **Update method:** Mutate in place. The existing widget's text label and count badge update — no widget destruction, no new widget creation. This means **no scroll trigger** on update (counter changes don't push the chat).

**Why mutate, not recreate:** Recreating would trigger the same scroll problem we're trying to solve. Mutating keeps the bubble stable in the container; only its text content changes. The user sees the count tick up but the chat doesn't move.

**Implementation:**

- `models/activity.py`: add new aggregate type `"counter"` (a new bubble kind) with fields: `count: int`, `last_text: str`, `total_duration_ms: int`, `last_command: str`, `type: ActivityType` (the type being counted).
- `ui/handlers/activity_handler.py`: introduce a per-session counter store. On each bubble emission:
  1. Check if there's an open counter for `(session_key, agent_turn, type)`.
  2. If yes: increment its count, update `last_text` / `total_duration_ms` / `last_command`, fire a `mutate` callback (NOT a new bubble emission). **The counter widget updates in place via the mutate callback.**
  3. If no: close any open counter of a different type for this session+turn, then create a new counter bubble with `count=1`.
- `ui/handlers/chat_render_handler.py:589`: add a `render_counter_bubble()` branch. Returns a mutable widget with an `update(count, last_text, total_duration_ms, last_command)` method.
- `ui/views/chat_bubble.py`: add CSS for `activity-counter` class — the count badge is a small highlighted chip (e.g., indigo background, white text, rounded). The bubble itself has the same general shape as other pills but with the count as a prominent prefix.
- `ui/views/main_content.py`: counter bubbles are children of the System Bubble Container (Fix 1.4), not direct chat children.

**Cost:** ~1.5-2 days. Reuses the System Bubble Container from Fix 1.4, so the integration is mostly a counter-state machine + a widget with a mutator method.

**Relationship to other fixes:**
- **Depends on Fix 1.4 (System Container).** Counters live inside the container; without the container, this is just a fancier version of the original EXEC-pile problem.
- **Complements Fix 1.5 (Content Enrichment).** The counter shows `last command` so Fix 1.5's command-string capture is the data source. Without Fix 1.5, the counter would show `exec ×5  4,247ms` (no command string).
- **Does NOT need Tier 2.1 (Throttle).** Counters naturally bound the count rate — 5 EXEC in 200ms is still 1 counter incrementing 5 times, not 5 separate widgets. Tier 2.1 throttle is **redundant** once counters ship and should be removed from Tier 2.

**Edge cases handled:**
- Exit code ≠ 0: counter shows `exec ×5  last failed  4,247ms` (or equivalent) so failures are visible.
- Mixed success/failure: counter could optionally show `exec ×4  1 fail  4,247ms`.
- Lifecycle boundaries: a new `lifecycle_start` event closes the previous counter and starts fresh. The counter doesn't carry across agent turns.

#### Fix 1.2 — Add a "Show activity bubbles" toggle to the chat toolbar

**Current:** Bubbles always render. The user cannot opt out at the per-session level.

**Proposed:** A small toggle in the chat control bar (the existing `ChatControlBar` is currently stubbed — see `ui/views/chat_bubble.py` and `main_content.py:493`). When off:
- All activity bubble emissions are silently dropped (no widget created, no scroll trigger)
- The FeedBar continues to function normally — the state, progress, and velocity remain visible
- Setting persists in `MainContent._show_activity_bubbles` (in-memory per session — no need to persist across sessions)

**Implementation:**
- `ui/views/chat_bubble.py`: add a toggle button in the `ChatControlBar`. Pass a callback up to `ChatHandler` → `ActivityHandler`.
- `ui/handlers/activity_handler.py`: in `on_gateway_event`, when emitting an activity bubble, check `MainContent._show_activity_bubbles` first. If false, drop the bubble but still update the FeedBar state.
- The toggle state is owned by `MainContent` (composition root) and read by `ActivityHandler` via a getter — same pattern as `_is_ui_active`.

**Cost:** ~0.5 days. Low risk. Gives power users the data, gives focus-seekers the silence. **No persistence needed** — fresh session, fresh default (on). User who wants it off every time can flip it once and not worry.

#### Fix 1.3 — Stop auto-scrolling on activity bubbles

**Current:** Every activity bubble render triggers `self._mc.scroll_chat_to_bottom()`. The chat snaps to the bottom even if the user is reading older content.

**Proposed:** Activity bubble renders do *not* trigger scroll-to-bottom. They append the widget to the container and that's it. If the user is already near the bottom, the natural GTK behavior will scroll them to the new content; if they're scrolled up reading, the new bubble appears below their viewport without yanking them down.

**Implementation:**
- `ui/handlers/chat_handler.py`: in the activity bubble emission path (the `set_on_activity_bubble` callback at line 187-192), do **not** call `self._mc.scroll_chat_to_bottom()`. Audit the 14 existing call sites and confirm none of them are tied to activity bubble emission — if any are, split them.
- `ui/views/main_content.py:718`: the existing `scroll_chat_to_bottom` is fine. The fix is purely in the caller (don't call it from the activity bubble path).

**Cost:** ~0.25 days. **One-line change** in the activity bubble emission path. Should be done *first* because it alone makes the current behavior tolerable even if nothing else changes.

#### Fix 1.4 — System Chat Bubble Container (the "system is chatting with you" model)

**Current:** Each individual pill bubble is a separate centered widget that appends directly to the main chat container. 30+ pills = 30+ rows in the chat = chat pushed off-screen.

**Proposed:** All activity pills emit into **one outer "System Chat Bubble"** — itself a single centered widget in the main chat, with bounded height and internal scrolling. The outer bubble represents one "agent turn" of system activity. Inside it, the individual pills stack vertically (newest at bottom) and scroll internally when they exceed the height cap. The main chat only sees one row per agent turn, not one row per pill.

**Visual model:**

```
[ User ]   Hey Coder, fix the auth flow
[ Coder ]  Working on it...
╔══════════════════════════════════════╗
║           System                     ║   ← ONE outer system bubble
║  ┌────────────┐  ┌────────────┐      ║      centered, bounded height
║  │ reading... │  │ exec  1.2s │  ▲   ║      inner pills scroll here
║  └────────────┘  └────────────┘  █   ║
║  ┌────────────┐  ┌────────────┐  █   ║
║  │ read  83ms │  │ exec  exit │  █   ║
║  └────────────┘  └────────────┘  ▼   ║
╚══════════════════════════════════════╝
[ User ]   Thanks!
[ Coder ]  Done — pushed the fix.
```

**Behavior decisions (confirmed with Captain):**

1. **One outer system bubble per agent turn** — when an agent run starts (`lifecycle_start`), a new outer bubble is created. When the agent ends (`lifecycle_end`), the outer bubble **persists** with all its pills scrollable inside. It does NOT collapse on idle. Each new agent turn creates a new outer bubble below the previous one.

2. **Newest pill at the bottom** — matches chat convention. User scrolls *up* inside the outer bubble to see history. Auto-scroll inside the outer bubble to keep the latest pill visible while a turn is active.

3. **Main chat scroll behavior** — the outer system bubble creation triggers a single `scroll_chat_to_bottom()` (so the user sees it appear). Individual pill emissions into an existing outer bubble do NOT trigger main chat scroll. The pill appears inside the existing bubble, scroll position in the main chat is preserved.

**Height cap and overflow:**

- The outer bubble has a `Gtk.ScrolledWindow` inside it, capped at approximately **3-4 pill rows** (~120-160px) by default.
- When pill count exceeds the cap, the inner `Gtk.ScrolledWindow` shows a scrollbar (subtle, fading) and the user can scroll to see history.
- Configurable: a setting in the future could expose this. For now, hardcode at 4 rows.

**Implementation:**

- `models/activity.py`: no new type needed — the aggregate bubble is a `Gtk.Box` wrapper, not a new `ActivityType`. Pills are still individual `ActivityBubble` objects emitted into the wrapper.
- `ui/handlers/activity_handler.py`: track outer bubble state per session. On `lifecycle_start`, create a new outer wrapper bubble. On every subsequent activity event in that turn, append the pill to the *existing* outer wrapper rather than the main chat container.
- `ui/views/chat_bubble.py`: add a new widget builder `build_system_bubble()` that returns a `Gtk.Box` containing a header label ("System") and an inner `Gtk.ScrolledWindow` with a vertical `Gtk.Box` for pill stacking. Height cap via `set_size_request(-1, 120)` plus a `Gtk.Viewport`.
- `ui/handlers/chat_handler.py`: the activity bubble emission path (currently calls `set_on_activity_bubble` callback) now resolves to the outer wrapper for the current turn. No new `scroll_chat_to_bottom()` call on per-pill emission.
- `ui/views/feedbar.py`: unchanged.

**Cost:** ~1.5-2 days. Higher than Fix 1.3 (one-line) but lower than Fix 1.1 (counter-collapse state machine). Higher impact than both because it solves the root cause: pills no longer compete with the main chat for vertical space.

**Visual benefit beyond the chat-fix:** the outer bubble creates a clear semantic — "this is the system telling you what it's doing" — distinct from the user/agent conversation. The header label "System" makes it scannable. Users who want to ignore the system bubble can (it sits centered, doesn't intrude on the conversation flow). Users who want to watch it can (one click expands, the inner scrollbar is always subtle but available).

**Relationship to other fixes:**
- Fix 1.1 (counter-collapse) and Fix 1.4 (container) are *complementary*. The container holds the bubbles; the counter collapses consecutive same-type bubbles inside the container. Together they reduce 30+ scattered pills to ~5-8 grouped counters.
- Fix 1.2 (toggle) and Fix 1.4 are *complementary*. The toggle can hide the outer bubble entirely; Fix 1.4 makes the outer bubble non-intrusive when shown.
- Fix 1.3 (no auto-scroll) is *absumed* by Fix 1.4. If pills no longer emit to the main chat, the per-pill scroll-to-bottom call is gone by construction. The remaining scroll-to-bottom call (for outer bubble creation) is correct and desired.

#### Fix 1.5 — Content Enrichment: show the command and the agent (client-side correlation)

**Current:** Every `command_output` pill shows only the tool name (`exec`) and duration. The actual command string (e.g., `pytest tests/test_auth.py`) is missing. The agent name (e.g., `Coder`, `Researcher`) is missing. The data is useless for understanding what the agent is doing.

**Proposed:** Capture the command string and agent name on the **client side** by correlating `tool_call_start` (which already receives both) with the subsequent `command_output` event (which only receives the tool name). The command and agent get attached to the bubble at render time.

**Why client-side (not gateway):** CrabCakes does not own the OpenClaw gateway — it's a separate project. The gateway currently broadcasts `command_output` with `name: "exec"`, `exitCode`, and `durationMs` only. It does not include the command string or agent name. **We cannot fix the gateway from this codebase.** Client-side correlation is the only path available.

**Caveat — verify the gateway is not already sending it under a different key:** Before implementing correlation, the team should add a one-time debug log at `ui/handlers/activity_handler.py:308` that prints the full `data` payload of a `command_output` event. If `data["command"]` or similar is already present, we skip correlation entirely and just extract the field. **This is a 10-minute investigation that could save 4-6 hours of work.**

**Implementation (assuming the gateway does NOT send it):**

1. **Track active tools per session.** In `AgentRuntime` / `agent_runtime_handler.py`, when `_on_tool_call_start` fires (around line 540), store `(session_key, agent_name, tool_name, command_args)` in an in-memory cache keyed by `session_key`. When `_on_tool_call_result` fires, remove the entry. The cache is bounded (one entry per session) and thread-safe via `GLib.idle_add`.

   ```python
   # In agent_runtime_handler.py
   def _do_tool_call_start(self, session_key, name, args):
       # ...existing feed card code...
       
       # NEW: stash for ActivityHandler correlation
       agent_def = self._agents.get(session_key)
       agent_name = agent_def.display_name if agent_def else "Agent"
       self._active_tools[session_key] = {
           "agent_name": agent_name,
           "tool_name": name,
           "command": args.get("command", "") if name == "exec_command" else "",
       }
   
   def _do_tool_call_result(self, session_key, name, result):
       # ...existing feed card code...
       self._active_tools.pop(session_key, None)
   ```

2. **Expose the cache to ActivityHandler.** Add a method `get_active_tool(session_key) -> dict | None` to `AgentRuntime` (or pass the cache directly via constructor). ActivityHandler calls it inside the `command_output` handler.

3. **Enrich the bubble.** In `ui/handlers/activity_handler.py:305-315`, before creating the `ActivityBubble`, look up the active tool for `session_key` and grab the cached `command` and `agent_name`.

   ```python
   elif stream == "command_output":
       data = payload.get("data", {})
       if data.get("phase") == "end":
           name = data.get("name", "") or ""
           exit_code = data.get("exitCode", 0)
           duration_ms = data.get("durationMs", 0)
           sk = payload.get("sessionKey", "") or session_key
           
           # NEW: look up cached command + agent
           cached = self._active_tool_lookup(sk) if self._active_tool_lookup else None
           cmd = cached.get("command", "") if cached else ""
           agent = cached.get("agent_name", "") if cached else ""
           
           if name and self._activity_bubble_callback:
               bubble = ActivityBubble(
                   type="command_output",
                   session_key=sk,
                   tool_name=name,
                   command=cmd,        # NEW field
                   agent_name=agent,   # NEW field
                   exit_code=exit_code,
                   duration_ms=duration_ms,
                   icon="💻"
               )
               self._activity_bubble_callback(bubble)
   ```

4. **Update the model.** Add `command: str = ""` and `agent_name: str = ""` to `ActivityBubble` in `models/activity.py`. Both already have dataclass fields, just need to extend the type and add defaults.

5. **Update the formatter.** In `models/activity.py:format_text()`, the `command_output` branch becomes:

   ```python
   elif self.type == "command_output":
       name = _friendly_tool_name(self.tool_name)
       ms = self.duration_ms
       cmd = self.command
       if len(cmd) > 60:
           cmd = cmd[:57] + "..."
       agent = self.agent_name
       # Default: "exec  pytest tests/...  1,247ms"
       # With agent: "Coder  exec  pytest tests/...  1,247ms"
       prefix = f"{agent}  " if agent else ""
       cmd_part = f"  {cmd}" if cmd else ""
       if self.exit_code != 0:
           return f"{prefix}{name}{cmd_part}  exit {self.exit_code}  {ms:,}ms"
       return f"{prefix}{name}{cmd_part}  {ms:,}ms"
   ```

6. **Apply the same enrichment to `tool_start` / `tool_end` bubbles** so the agent name appears on all 8 types, not just `command_output`. The `name` field for tools is already informative (`read_file`, `web_search`) but adding the agent prefix makes the system self-explanatory.

**Visual result after Fix 1.5:**

```
[Coder]  exec  pytest tests/test_auth.py  1,247ms
[Coder]  read  ui/views/main.py
[Researcher]  web_search  "openclaw gateway schema"
[Researcher]  fetch  https://docs.openclaw.ai  832ms
[Coder]  exec  git commit -m "fix auth"  340ms
```

**Cost:** 4-6 hours if the gateway does NOT send the command string. 10 minutes if it does and we just need to extract it. The first 10 minutes of work (adding a debug log and triggering one command) determines the actual cost.

**Risk:** Medium. The correlation relies on the `tool_call_start` event arriving before `command_output` for the same session. This is normally true because the tool call is what triggers the command execution. But under race conditions (parallel tools, multiple sessions in the same WebSocket), the cache could return the wrong entry. Mitigation: key the cache by `(session_key, tool_call_id)` instead of just `session_key`, and add a TTL (e.g., 30s) so stale entries self-evict.

**Relationship to other fixes:**
- Fix 1.4 (System Bubble Container) and Fix 1.5 are *complementary* — 1.4 fixes the delivery, 1.5 fixes the content. Both should ship.
- Fix 1.5 makes Fix 1.1 (counter-collapse) *less needed* — if each pill shows the actual command, the user has more reason to want to see them all (rather than collapsed into a summary).
- The agent name (e.g., `Coder`) is redundant with the session tab label in some cases — but in a multi-agent project (Coder + Researcher + Reviewer), it provides clear attribution.

### Tier 2 — Refinements (1-2 weeks, polish layer)

These improve the system without being urgent. **Fix 2.1 (Throttle) is removed** — Fix 1.1's counter-collapse makes it redundant.

#### ~~Fix 2.1 — Throttle activity bubble emission to 1 per 1.5s~~  *(removed — Fix 1.1 counters cover this)*

**Cost:** ~1 day.

#### Fix 2.2 — Auto-expire non-signal activity bubbles after 30s

When a new bubble of the same type appears, the old one fades out (opacity 1.0 → 0.0 over 500ms via `GLib.timeout_add`).

The `lifecycle_start` and `approval_request` bubbles are signal — they need to persist until a newer event of the same kind. The other 6 are noise — they should auto-expire.

**Cost:** ~2 days. Requires a small per-bubble timer system. Bounded memory risk if not careful — must hold a reference to the GLib source ID per bubble so it can be cancelled if the session is closed.

#### Fix 2.3 — Distinguish "signal" from "noise" by type via CSS

Some types are intrinsically high-value (`approval_request` — needs user action, the user *must* see this). Some are low-value (`command_output` — post-hoc fact).

Add CSS classes per type and style them differently:
- `activity-approval-request` — full opacity, larger, distinct color (warm red or amber), slightly raised
- `activity-lifecycle-start` — full opacity, distinct
- `activity-tool-*`, `activity-command-output`, `activity-patch` — 60% opacity, smaller, gray

The CSS class system is already in place (`activity-{type}` per `chat_render_handler.py:600`) — just need different styles per class in the stylesheet.

**Cost:** ~1 day. Mostly CSS, very low risk.

---

## How

### Files to Change

| File | Tier 1 changes | Tier 2 changes |
|------|---------------|---------------|
| `models/activity.py` | Add `command` and `agent_name` fields | Add expiration field |
| `ui/handlers/activity_handler.py` | Active tool cache; command/agent enrichment | Throttle, auto-expire timers |
| `ui/handlers/agent_runtime_handler.py` | Stash `(session_key, agent_name, command)` in cache | — |
| `ui/handlers/chat_handler.py` | Stop scrolling on bubbles | — |
| `ui/handlers/chat_render_handler.py` | System bubble container widget branch | — |
| `ui/views/chat_bubble.py` | Add toggle in ChatControlBar; add `build_system_bubble()` | CSS per type |
| `ui/views/main_content.py` | `_show_activity_bubbles` state; outer bubble per agent turn | — |
| `ui/views/feedbar.py` | — | — (unchanged) |

### Test Coverage

Each fix gets tests. Total expected: ~15-18 new tests across Tier 1+2.

| Test class | Tests | What |
|------------|-------|------|
| `TestCounterCollapse` | 6 | Same-type counter increments, different-type closes, mutate in place, lifecycle boundary, exit code display, total duration math |
| `TestSystemBubbleContainer` | 5 | Created on lifecycle_start, pills append, height cap, inner scroll, persists on lifecycle_end |
| `TestSystemBubblePillRouting` | 3 | Pills route to outer container, not main chat, across all 8 types |
| `TestActivityBubbleContentEnrichment` | 4 | Command string captured from cache, agent name captured, cache TTL, missing-cache fallback |
| `TestActivityBubbleToggle` | 2 | Toggle state suppresses emission, FeedBar still updates |
| `TestActivityBubbleNoScroll` | 1 | Per-pill emission doesn't trigger main chat scroll |
| `TestActivityBubbleThrottle` | 2 | 1.5s throttle inside outer bubble, "+N more" suffix |
| `TestActivityBubbleExpiration` | 3 | 30s expiry, lifecycle persists, approval persists |
| `TestActivityBubbleSignalVsNoise` | 3 | CSS class per type, opacity per type |

**Test class `TestActivityBubbleCollapse` is removed** (Fix 1.1 is now a general counter-collapse, not a per-EXEC log). **Test class `TestCounterCollapse` is new** for the new Fix 1.1.

### Migration

Tier 1 changes are **additive with no breaking changes**. Two new fields are added to `ActivityBubble` (`command`, `agent_name`). The toggle is opt-in. The scroll suppression is a behavior change but the only effect is "chat doesn't auto-scroll to activity bubbles anymore" — strictly less surprising.

Tier 2 changes are also additive. Auto-expiration uses GLib timers that get cancelled on session close. Throttling is in-memory.

### Open Questions

1. **Outer system bubble header label.** The proposal uses "System" as the centered header text. Alternatives: a small icon + "System", "● Activity", or no header (just a thin top border). The header is what makes the bubble scannable. Captain's preference?

2. **Inner scrollbar visibility.** The proposal suggests a subtle, fading scrollbar. Alternatives: always visible, hidden until hover, or a custom-styled thin bar on the right edge. Hidden-until-hover is the most modern (macOS-style) but harder to discover. Captain's preference?

3. **What should `activity-bubble` CSS opacity be by default?** The current code at `chat_render_handler.py:600-602` has no opacity hint. Tier 2.3 proposes 60% for noise types. Captain's preference?

4. **Should the toggle persist across sessions?** The current proposal says no (in-memory only). The alternative is to add a setting in `~/.config/crabcakes/config.json` and load it at startup. More work, more flexibility. Captain's call.



6. **Should the outer system bubble have a close/dismiss button?** If the user is done with a turn's activity log, can they collapse it? Or is it always scrollable? Captain's preference?

---

## Success Metrics

The success criteria for this proposal are qualitative (does the chat feel less like it's running away?) but we can measure:

| Metric | Before | After (Tier 1 target) | After (Tier 2 target) |
|--------|--------|----------------------|----------------------|
| Visible bubble widgets per 10-min Coder session | 30-50 | 5-8 (counter-collapsed) inside 1 outer scrollable | 3-5 |
| Vertical pixels consumed in main chat by activity | 1,400px | 120-160px (one outer bubble per turn) | 120-160px |
| Main chat scroll triggers per session | 30-50 | 1-3 (one per outer bubble) | 1-3 |
| User-initiated scroll-to-bottom button presses per session | High (chat keeps yanking) | Low (chat stays put) | Low |
| Toggle-off usage rate | N/A | TBD after 1 week | TBD |
| Pill content informativeness (% showing actual command + agent) | 0% (only "exec") | 95%+ (Fix 1.5) | 99%+ |

**Note on the bubble count metric:** with Fix 1.4, the *outer* bubble count drops to 1 per agent turn, but the *inner* pill count stays at 30+. The metric shifts from "bubbles pushing chat" to "bubbles scrollable inside a contained area." The vertical pixel metric is the more honest one.

**Note on content informativeness:** the "informativeness" metric measures how many pills carry the actual command string and agent name, rather than just the tool name (`exec`). Pre-Fix 1.5, this is 0% — every pill shows `exec  1,247ms`. Post-Fix 1.5, this should be 95%+ (with a fallback for the rare case where the cache lookup fails).

---

## Recommendation

**Do Tier 1.3, 1.5, 1.4, 1.1, 1.2 in that order. Total cost: ~6-7 days. High impact, low risk.**

- **Tier 1.3 (one-line scroll fix)** is the highest-leverage change and should ship first — possibly standalone as a quick patch. It alone makes the current behavior tolerable.

- **Tier 1.5 (Content Enrichment)** should ship second. It is **independent** of the UX fixes — it changes the *content* of the pills, not their *delivery*. Once the command string and agent name appear, the user has the data they wanted ("what is being exec'd and who") regardless of how the pills are displayed. **Note:** Step 0 is a 10-minute investigation (add a debug log to see what the gateway actually sends) that may reduce Fix 1.5 from 4-6 hours to 10 minutes.

- **Tier 1.4 (System Chat Bubble Container)** should ship third. It solves the root cause: pills no longer compete with the main chat for vertical space. Provides the container that Fix 1.1's counters will live inside.

- **Tier 1.1 (Counter-Collapse)** should ship fourth. Now a general-purpose counter for any same-type bubble run. Depends on Fix 1.4 (counters live inside the container) and Fix 1.5 (counters show the last command). Mutates in place — no scroll trigger.

- **Tier 1.2 (toggle)** is the escape hatch and should ship fifth. Power users who want to see the outer bubble can; focus-seekers can hide it entirely.

**Revised ship order:** 1.3 → 1.5 → 1.4 → 1.2. ~4-5 days total.

Hold the remaining Tier 2 fixes (2.2, 2.3) for after Tier 1 has been in production for at least a week. The Tier 1 changes may be enough on their own. If the Captain still finds the experience annoying, Tier 2.2 (auto-expire noise pills) and Tier 2.3 (signal/noise CSS) are the next best moves. **Tier 2.1 (throttle) is removed** — Fix 1.1 counters make it redundant.

**One thing I would *not* do:** remove EXEC bubbles entirely. The data is valuable. The complaint is not "too much information" — it's "information delivered in a way that interferes with the conversation." Quiet the delivery, keep the data.

---

**Standing by for your decision, Captain.** This proposal is ready for review. If approved, I'd recommend a 6-7 day implementation sprint for Tier 1 (1.3, 1.5, 1.4, 1.1, 1.2), followed by a 1-week observation period before deciding on the remaining Tier 2 fixes (2.2, 2.3).
