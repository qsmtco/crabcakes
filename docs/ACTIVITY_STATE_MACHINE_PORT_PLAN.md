# Activity State Machine — Porting Plan

**Source:** `/home/q/projects/deadcode/src/app.py` (Phase 6 — "New activity state machine")
**Target:** `/home/q/projects/crabcakes`
**Philosophy:** Minimal, handler-contained, strictly architecture-compliant. window.py gets ≤10 lines of new composition code. main_content.py gets zero new logic — all state machine state lives in the handler.

---

## Background

The deadcode `app.py` implements a 6-state activity state machine visible in the top bar above chat tabs:

| State | Label | Progress Bar |
|-------|-------|-------------|
| `idle` | ● Idle (green) | Subtle pulse (0.3 opacity, 100ms) |
| `sending` | ⬡ Pre Flight Check (amber) | 5% fraction |
| `reasoning` | ◉ Reasoning… (amber) | 10%→30% over 5s |
| `streaming` | ⬇ Generating… + live counters (blue) | 30%→95% based on char count |
| `tool_use` | ⚙ {tool} (purple) | 30%→95% based on char count |
| `done` | ✓ Done (green) | 100%, then → idle after 5s |

The bar also shows live counters during `streaming`: token estimate, velocity (tok/s), elapsed time.
The progress bar is a 2px `Gtk.ProgressBar` with an animated gradient.

---

## Architecture Constraints

1. **Handler pattern mandatory** — Section 8.6 of ARCHITECTURE.md: all new UI logic → `ui/handlers/`
2. **FeedBar = "Response Status" bar** — the state machine label and progress bar live in `ui/views/feedbar.py`
3. **window.py minimal** — only creates the handler, injects dependencies, wires one callback
4. **main_content.py zero new logic** — handler reads active session from `main_content.get_current_session_key()` via injected reference
5. **CSS in styles.py** — progress bar styling goes in `APP_CSS` only
6. **Thread safety** — all GTK calls via `GLib.idle_add()`

---

## Source State (deadcode app.py key lines)

```
State variables:
  self._activity_state = "idle"
  self._first_delta_seen = False
  self._live_update_timer = None      # GLib source
  self._done_flash_timers = {}         # session_key → GLib source
  self._idle_pulse_timer = None        # GLib source
  self._current_tool_name = ""
  self._streaming_token_count = 0
  self._agent_start_time = {}          # session_key → monotonic

Trigger points (window → state machine):
  agent phase=start  → set_activity("reasoning")
  agent phase=end     → set_activity("done")
  agent phase=error   → set_activity("idle")
  tool_use event      → set_activity("tool_use")
  first chat delta    → set_activity("streaming")
  agent message recv  → set_activity("sending")  [pre-flight]

FeedBar update (_update_top_bar):
  Updates label with state text + live counters
  Updates progress bar fraction / pulse / opacity

Progress bar fraction logic:
  idle:        pulse() every 100ms, opacity=0.3
  sending:     fraction=0.05
  reasoning:   fraction = 0.10 + (elapsed/5.0)*0.20, capped 0.30
  streaming:   fraction = 0.30 + min(char_count/2000, 1.0)*0.65
  tool_use:    same as streaming (based on char_count)
  done:        fraction=1.0, then auto-idle after 5s

FeedBar label (streaming state — live counters):
  token_est = streaming_token_count // 4
  elapsed = time.monotonic() - start
  velocity = token_est / elapsed
  → "Generating…  {token_est} tokens  ·  {vel_str}  ·  {elapsed_str}s"
```

---

## Phases

### Phase 1 — CSS + FeedBar Widget Update

**Files touched:** `ui/styles.py`, `ui/views/feedbar.py`

**Goal:** Give FeedBar the GTK widgets it needs (label + progress bar) and add the progress bar CSS.

**Changes:**

`ui/styles.py` — add CSS for `.response-progress`:
```css
.response-progress {
    margin-top: 2px;
    margin-bottom: 0;
    min-height: 2px;
    border-radius: 1px;
}
.response-progress trough {
    background: rgba(99, 102, 241, 0.1);
    border-radius: 1px;
    min-height: 2px;
}
.response-progress progress {
    background: linear-gradient(90deg, #6366f1, #3b82f6, #6366f1);
    background-size: 200% 100%;
    border-radius: 1px;
    min-height: 2px;
    animation: progress-stripe 1.5s linear infinite;
}
@keyframes progress-stripe {
    from { background-position: 0 0; }
    to { background-position: 40px 0; }
}
```

`ui/views/feedbar.py` — add progress bar as a child widget:
- Wrap content in a `Gtk.Box(VERTICAL)` — label on top, progress bar below
- Replace the single `_feed_label` with:
  - `_status_label` — Gtk.Label for the state text
  - `_progress_bar` — Gtk.ProgressBar with `.response-progress` CSS class
- Add `_build_widget()` private method constructing the vertical layout
- Add `set_progress(fraction)` and `set_pulse(enable)` helper methods
- Add `set_status_text(markup)` helper method

**Rationale:** Keeping all widget construction in the view (FeedBar). Handler only manipulates via public API.

---

### Phase 2 — ActivityHandler (Core State Machine)

**Files created:** `ui/handlers/activity_handler.py`
**Files touched:** `ui/views/feedbar.py` (public API methods only)

**Goal:** Extract all state machine logic into a handler. FeedBar is a pure view — manipulated only through its public API.

**ActivityHandler class:**

```python
# ui/handlers/activity_handler.py

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib

import time

class ActivityHandler:
    """
    Activity state machine — drives the Response Status bar (FeedBar).

    States: idle | sending | reasoning | streaming | tool_use | done

    Owns:
      - All state machine state (timers, counters, timestamps)
      - FeedBar widget reference (injected via constructor)
      - MainContent reference (for get_current_session_key())

    Thread safety: all GTK calls via GLib.idle_add().
    All entry points are called from the GTK main thread (gateway callbacks are
    already GLib-dispatched by GatewayHandler).

    Public API (called by window.py's gateway/event callbacks):
      on_agent_start(session_key, data)          → set_reasoning
      on_agent_end(session_key, data)            → set_done + 5s timer
      on_agent_error(session_key, data)          → set_idle
      on_tool_use(tool_name, session_key, data)  → set_tool_use
      on_chat_delta(delta_text, session_key)     → first delta → set_streaming
      on_agent_message_received(session_key)      → set_sending (pre-flight)

    Window wires these to gateway event types in _on_ws_event.
    """

    _STATES = ("idle", "sending", "reasoning", "streaming", "tool_use", "done")

    _STATE_CONFIG = {
        "idle":      (False, False),  # (show_progress, pulsing)
        "sending":   (True,  False),  # fraction=0.05
        "reasoning": (True,  False),  # fraction=0.10..0.30 (time-based)
        "streaming": (True,  False),  # fraction=0.30..0.95 (char-based)
        "tool_use":  (True,  False),  # same as streaming
        "done":      (True,  False),  # fraction=1.0
    }

    def __init__(self, feedbar, main_content, GLib_module=None):
        self._feedbar = feedbar
        self._mc = main_content
        self._GLib = GLib_module or GLib

        # State machine state
        self._state = "idle"
        self._streaming_token_count = 0
        self._first_delta_seen = False
        self._current_tool_name = ""

        # Timers (GLib source IDs)
        self._live_update_timer = None
        self._idle_pulse_timer = None
        self._done_flash_timer = None

        # Per-session timing
        self._agent_start_time = {}  # session_key → monotonic

    # ── Public entry points (called from gateway event handlers in window) ──

    def on_agent_start(self, session_key, data=None):
        """agent phase=start — enter reasoning state."""
        sk = self._active_session()
        self._agent_start_time[sk] = time.monotonic()
        self._streaming_token_count = 0
        self._first_delta_seen = False
        self._current_tool_name = ""
        self._set_state("reasoning", sk)

    def on_agent_end(self, session_key, data=None):
        """agent phase=end — enter done state, auto-idle after 5s."""
        sk = self._active_session()
        self._agent_start_time.pop(sk, None)
        self._set_state("done", sk)
        self._start_done_flash(sk)

    def on_agent_error(self, session_key, data=None):
        """agent phase=error — return to idle immediately."""
        self._set_state("idle", session_key)

    def on_tool_use(self, tool_name, session_key, data=None):
        """tool_use event — enter tool_use state."""
        self._current_tool_name = tool_name or ""
        self._set_state("tool_use", session_key)

    def on_chat_delta(self, delta_text, session_key):
        """chat delta (streaming) — first delta transitions to streaming state."""
        sk = self._active_session()
        count = len(delta_text) if delta_text else 0
        self._streaming_token_count += count

        if not self._first_delta_seen:
            self._first_delta_seen = True
            self._set_state("streaming", sk)

    def on_agent_message_received(self, session_key):
        """agent message in history — pre-flight signal (brief sending state)."""
        sk = self._active_session()
        self._set_state("sending", sk)

    def on_chat_final(self, session_key):
        """chat final — no state change here; on_agent_end handles completion."""
        pass

    # ── State machine internals ─────────────────────────────────────────────

    def _active_session(self):
        """Return the currently active session_key from MainContent."""
        if self._mc:
            return self._mc.get_current_session_key()
        return None

    def _set_state(self, state, session_key):
        """Transition to a new state, cleaning up old timers and starting new ones."""
        if state == self._state:
            return

        self._state = state

        # Clean up all timers from previous state
        self._stop_live_update()
        self._stop_idle_pulse()
        self._stop_done_flash()

        # Apply state to FeedBar
        self._update_feedbar()

        # Start timers for new state
        if state in ("reasoning", "streaming", "tool_use"):
            self._live_update_timer = self._GLib.timeout_add(200, self._live_update)
        elif state == "idle":
            self._start_idle_pulse()
        elif state == "done":
            pass  # done flash started by caller

    def _update_feedbar(self):
        """Update FeedBar label + progress bar to reflect current state."""
        state = self._state

        # Build status label markup
        if state == "idle":
            text = '<span foreground="#4ade80">● Idle</span>'
            self._feedbar.set_progress_hidden(True)
        elif state == "sending":
            text = '<span foreground="#f59e0b">⬡ Pre Flight Check</span>'
            self._feedbar.set_progress_fraction(0.05)
        elif state == "reasoning":
            text = '<span foreground="#f59e0b">◉ Reasoning…</span>'
            self._feedbar.set_progress_fraction(self._reasoning_fraction())
        elif state == "streaming":
            text = self._streaming_label()
            self._feedbar.set_progress_fraction(self._streaming_fraction())
        elif state == "tool_use":
            tool = self._GLib.idle_add(self._escape_markup, self._current_tool_name)
            text = f'<span foreground="#a855f7">⚙ {tool}</span>'
            self._feedbar.set_progress_fraction(self._streaming_fraction())
        elif state == "done":
            text = '<span foreground="#4ade80">✓ Done</span>'
            self._feedbar.set_progress_fraction(1.0)

        self._feedbar.set_status_text(text)

    def _reasoning_fraction(self):
        """0.10 to 0.30 based on elapsed time (5s max)."""
        sk = self._active_session()
        start = self._agent_start_time.get(sk)
        if not start:
            return 0.10
        elapsed = time.monotonic() - start
        return min(0.10 + (elapsed / 5.0) * 0.20, 0.30)

    def _streaming_fraction(self):
        """0.30 to 0.95 based on character count (2000 chars = full range)."""
        char_count = self._streaming_token_count
        token_progress = min(char_count / 2000.0, 1.0)
        return 0.30 + token_progress * 0.65

    def _streaming_label(self):
        """Build live counter label for streaming state."""
        sk = self._active_session()
        token_est = self._streaming_token_count // 4
        start = self._agent_start_time.get(sk)
        elapsed = time.monotonic() - start if start else 0
        elapsed_str = f"{elapsed:.1f}s"
        velocity = token_est / elapsed if elapsed > 0.1 else 0
        vel_str = f"{velocity:.0f} tok/s"
        return (
            f'<span foreground="#3b82f6">⬇ Generating…</span>'
            f' <span foreground="#6b6b7a" font_desc="Sans 9">{token_est} tokens</span>'
            f' <span foreground="#4a4a5a" font_desc="Sans 9">·</span>'
            f' <span foreground="#6b6b7a" font_desc="Sans 9">{vel_str}</span>'
            f' <span foreground="#4a4a5a" font_desc="Sans 9">·</span>'
            f' <span foreground="#6b6b7a" font_desc="Sans 9">{elapsed_str}</span>'
        )

    def _escape_markup(self, text):
        """Escape text for Pango markup (simple & < > replacement)."""
        return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))

    # ── Timer callbacks ────────────────────────────────────────────────────

    def _live_update(self):
        """Called every 200ms during reasoning/streaming/tool_use — update counters."""
        if self._state not in ("reasoning", "streaming", "tool_use"):
            return False
        self._update_feedbar()
        return True

    def _start_idle_pulse(self):
        """Start the idle pulse animation on the progress bar."""
        self._feedbar.set_progress_pulse(True)
        self._idle_pulse_timer = self._GLib.timeout_add(100, self._idle_pulse)

    def _idle_pulse(self):
        """Tick for idle pulse — pulse the progress bar."""
        if self._state != "idle":
            return False
        self._feedbar.pulse_progress()
        return True

    def _start_done_flash(self, session_key):
        """Start 5-second done→idle flash timer."""
        def expire():
            if self._state == "done":
                self._set_state("idle", session_key)
            return False
        self._done_flash_timer = self._GLib.timeout_add_seconds(5, expire)

    # ── Timer cleanup ─────────────────────────────────────────────────────

    def _stop_live_update(self):
        if self._live_update_timer is not None:
            self._GLib.source_remove(self._live_update_timer)
            self._live_update_timer = None

    def _stop_idle_pulse(self):
        if self._idle_pulse_timer is not None:
            self._GLib.source_remove(self._idle_pulse_timer)
            self._idle_pulse_timer = None
        self._feedbar.set_progress_pulse(False)

    def _stop_done_flash(self):
        if self._done_flash_timer is not None:
            self._GLib.source_remove(self._done_flash_timer)
            self._done_flash_timer = None
```

**FeedBar public API additions** (Phase 1):
```python
def set_status_text(self, markup): ...
def set_progress_fraction(self, fraction): ...
def set_progress_hidden(self, hidden): ...
def set_progress_pulse(self, enable): ...
def pulse_progress(self): ...
```

---

### Phase 3 — Wiring in window.py

**Files touched:** `ui/window.py`

**Goal:** Create ActivityHandler in `_build()`, inject FeedBar + MainContent, wire gateway events to handler.

**Changes to `window.py`:**

1. Import `ActivityHandler`
2. In `_build()`, after FeedBar construction:
   ```python
   # Activity handler — owns the Response Status state machine (Phase N)
   self._activity_handler = ActivityHandler(
       feedbar=self._response_status,
       main_content=self._main_content,
       GLib_module=GLib,
   )
   ```
3. In `_on_ws_event()` — route activity events to handler:
   ```python
   def _on_ws_event(self, event, payload):
       session_key = payload.get("sessionKey", "")

       if event == "chat":
           state = payload.get("state", "")
           if state == "delta":
               text = payload.get("text", "") or ""
               self._activity_handler.on_chat_delta(text, session_key)
           elif state == "final":
               self._activity_handler.on_agent_end(session_key)
           self._chat_handler.on_chat_event(event, payload)

       elif event == "agent":
           phase = payload.get("phase", "")
           if phase == "start":
               self._activity_handler.on_agent_start(session_key, payload)
           elif phase == "end":
               self._activity_handler.on_agent_end(session_key, payload)
           elif phase == "error":
               self._activity_handler.on_agent_error(session_key, payload)

       elif event == "tool_call":
           tool_name = payload.get("tool_name", "")
           self._activity_handler.on_tool_use(tool_name, session_key, payload)
   ```

**Window.py new code: ~12 lines total** (import + constructor + wiring in `_on_ws_event`).

---

### Phase 4 — ARCHITECTURE.md Update

**Files touched:** `docs/ARCHITECTURE.md`

**Changes:**

- Section 2 (directory structure): add `activity_handler.py` to `ui/handlers/`
- Section 3: add new Section 3.21 `ui/handlers/activity_handler.py`
- Section 3: update FeedBar section (3.20 or wherever it is) to document the new public API methods
- Section 4 (data flow): add Activity State Machine flow diagram
- Section 11 (file inventory): update file line counts

**Section 3.21 content:**

```markdown
### 3.21 ui/handlers/activity_handler.py — Activity State Machine (Phase N)

**Responsibility:** The 6-state activity machine that drives the Response Status bar (FeedBar). Manages state transitions, live timers, and FeedBar updates. Extracted from window.py in Phase N.

**Owns:** All state machine state (timers, counters, timestamps). Does NOT own any GTK widgets — manipulates FeedBar only through its public API.

**Does NOT own:** FeedBar or MainContent — received as constructor dependencies.

**Thread safety:** All GTK calls via `GLib.idle_add()`. Entry points are called from GTK main thread only.

**States:** idle | sending | reasoning | streaming | tool_use | done

**Public API:**
```python
def on_agent_start(session_key, data=None)      # agent phase=start
def on_agent_end(session_key, data=None)          # agent phase=end
def on_agent_error(session_key, data=None)       # agent phase=error
def on_tool_use(tool_name, session_key, data)   # tool_call event
def on_chat_delta(delta_text, session_key)      # first delta → streaming
def on_agent_message_received(session_key)       # pre-flight sending signal
```

**State transitions triggered by:**
- `agent` event with `phase=start` → `reasoning`
- `agent` event with `phase=end` → `done` (auto → `idle` after 5s)
- `agent` event with `phase=error` → `idle`
- `tool_call` event → `tool_use`
- First chat delta → `streaming`
- Agent message in history → `sending` (pre-flight)
```

**Section 4 data flow addition:**

```markdown
### 4.9 Activity State Machine

```
Gateway events → window._on_ws_event() → ActivityHandler methods
  agent phase=start  → on_agent_start()  → set_reasoning
  agent phase=end     → on_agent_end()    → set_done + 5s idle timer
  agent phase=error   → on_agent_error() → set_idle
  tool_call event    → on_tool_use()     → set_tool_use
  chat delta         → on_chat_delta()    → first delta: set_streaming
  agent message      → on_agent_message_received() → set_sending (pre-flight)

ActivityHandler → FeedBar public API:
  set_status_text(markup)              → updates state label
  set_progress_fraction(fraction)      → 0.0..1.0 bar fill
  set_progress_hidden(hidden)           → show/hide bar
  set_progress_pulse(enable)           → start/stop pulse
  pulse_progress()                      → one pulse tick
```

---

## File Summary

| Phase | File | Change |
|-------|------|--------|
| 1 | `ui/styles.py` | Add `.response-progress` CSS + keyframe animation |
| 1 | `ui/views/feedbar.py` | Refactor into vertical layout; add progress bar + public API methods |
| 2 | `ui/handlers/activity_handler.py` | **New file** — full state machine logic |
| 3 | `ui/window.py` | ~12 lines: import, construct handler, wire `_on_ws_event` to handler |
| 4 | `docs/ARCHITECTURE.md` | Document ActivityHandler in Section 3, 4, 11 |

---

## What's NOT Being Ported

The following deadcode features are intentionally omitted:

1. **`sending` state as pre-flight** — in deadcode this fires when an agent message appears in history. In crabcakes the gateway doesn't emit this event reliably. The `on_agent_message_received()` entry point exists but may not be wired if no gateway event maps to it.

2. **`_publish_to_feed()` integration** — deadcode publishes thinking/streaming events to the project feed. Crabcakes handles feed events differently (Phase 4 `render_event_card`). Activity state machine and project feed are separate concerns.

3. **`TopBarController` extraction** — deadcode has a thin `TopBarController` in `ui/topbar.py`. Crabcakes uses `FeedBar` instead. The thin wrapper pattern is replaced by the handler→view public API pattern.

4. **Hardcoded color values** — deadcode uses inline amber/green/blue hex values. These are CSS-only in the port; no hardcoded colors in Python.

---

## Verification Checklist

After each phase:
- [ ] Phase 1: FeedBar renders with label + progress bar visible; CSS loads without error
- [ ] Phase 2: `python3 -c "from ui.handlers.activity_handler import ActivityHandler; print('ok')"` — no import errors
- [ ] Phase 3: Connect to gateway; agent response should cycle through reasoning → streaming → done states
- [ ] Phase 3: Progress bar fraction changes during streaming (visible growth)
- [ ] Phase 3: `done` state auto-transitions to `idle` after 5 seconds
- [ ] Phase 3: `idle` state shows pulsing progress bar
- [ ] Phase 4: ARCHITECTURE.md updated in same commit as code
- [ ] All phases: Architecture guard tests pass (`pytest tests/test_architecture.py`)
