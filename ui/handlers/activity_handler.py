"""
ActivityHandler — 6-state activity machine driving the Response Status bar (FeedBar).

States: idle | sending | reasoning | streaming | tool_use | done

Transitions triggered by gateway events wired from window._on_ws_event():
  agent phase=start  → reasoning
  agent phase=end     → done (auto → idle after 5s)
  agent phase=error   → idle
  tool_call event    → tool_use
  first chat delta   → streaming
  agent message      → sending (pre-flight)

Owns all state machine state (timers, counters, timestamps).
Does NOT own FeedBar or MainContent — received as constructor dependencies.
Thread safety: all GTK calls via GLib.idle_add().
"""

from __future__ import annotations

import logging
import time
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from models.activity import ActivityBubble

_logger = logging.getLogger(__name__)


class ActivityHandler:
    _STATES = ("idle", "sending", "reasoning", "streaming", "tool_use", "done")
    PREFlight_TIMEOUT_SEC = 30

    def __init__(self, feedbar, main_content, GLib_module=None):
        self._feedbar = feedbar
        self._mc = main_content
        self._GLib = GLib_module or __import__("gi.repository.GLib", fromlist=["GLib"]).GLib

        # State machine state
        self._state = "idle"
        self._streaming_token_count = 0
        self._first_delta_seen = False
        self._current_tool_name = ""

        # Timers (GLib source IDs) — _done_flash_timers is per-session
        self._live_update_timer = None
        self._idle_pulse_timer = None
        self._done_flash_timers: dict[str, int] = {}  # session_key → GLib source ID
        self._send_initiated_timers: dict[str, int] = {}  # session_key → pre-flight timeout

        # Per-session timing
        self._agent_start_time: dict[str, float] = {}

        # Per-session progress tracking (two-phase: time-driven → event-driven)
        self._progress_start_time: dict[str, float] = {}  # session_key → send-initiated timestamp
        self._phase: dict[str, int] = {}  # session_key → 1 (time-driven) or 2 (event-driven)
        self._event_hop_count: dict[str, int] = {}  # session_key → number of gateway events received

        # Bug fix: state tracking for missing message recovery (Phase 1 of SPEC-smarter-chat-ux)
        self._assistant_text_buffer: dict[str, str] = {}    # session_key → last assistant text
        self._lifecycle_ended: dict[str, bool] = {}       # run_id → True when lifecycle end fired
        self._on_assistant_buffer: Callable[[str, str], None] | None = None  # buffer fwd callback
        self._lifecycle_completed_callback: Callable[[str, str], None] | None = None  # cb(sk, text)
        self._activity_bubble_callback: Callable[['ActivityBubble'], None] | None = None  # cb(bubble)
        self._on_agent_start_callback: Callable[[str], None] | None = None  # cb(sk) — clears render guard

    # ── Public entry points (called from gateway event handlers in window) ──

    def on_agent_start(self, session_key, data=None):
        """agent phase=start — enter reasoning state."""
        sk = self._active_session() or session_key
        self._agent_start_time[sk] = time.monotonic()
        self._streaming_token_count = 0
        self._first_delta_seen = False
        self._current_tool_name = ""
        self._set_state("reasoning", sk)
        # Clear render guard from previous round so new responses can render
        if self._on_agent_start_callback:
            self._on_agent_start_callback(session_key)

    def on_agent_end(self, session_key, data=None):
        """agent phase=end — enter done state, auto-idle after 5s."""
        sk = self._active_session() or session_key
        self._agent_start_time.pop(sk, None)
        self._reset_session_state(sk)
        self._set_state("done", sk)
        self._start_done_flash(sk)

    def on_agent_error(self, session_key, data=None):
        """agent phase=error — return to idle immediately."""
        sk = self._active_session() or session_key
        self._set_state("idle", sk)

    def on_tool_use(self, tool_name, session_key, data=None):
        """tool_call event — enter tool_use state."""
        self._current_tool_name = tool_name or ""
        sk = self._active_session() or session_key
        self._set_state("tool_use", sk)

    def on_chat_delta(self, delta_text, session_key):
        """chat delta (streaming) — first delta transitions to streaming state."""
        sk = self._active_session() or session_key
        count = len(delta_text) if delta_text else 0
        self._streaming_token_count += count

        if not self._first_delta_seen:
            self._first_delta_seen = True
            self._set_state("streaming", sk)

    def on_agent_message_received(self, session_key):
        """agent message in history — pre-flight signal (brief sending state)."""
        sk = self._active_session() or session_key
        self._set_state("sending", sk)

    def on_chat_final(self, session_key):
        """chat final — no state change here; on_agent_end handles completion."""
        pass

    def set_on_assistant_buffer(self, cb):
        """Set callback for buffering assistant text: cb(session_key, text).
        ActivityHandler calls this after every stream=assistant event so ChatHandler
        can maintain its own buffer for the missing-message recovery path.
        """
        self._on_assistant_buffer = cb

    def set_on_lifecycle_completed(self, cb):
        """Set callback for lifecycle end: cb(session_key, buffered_text).

        ActivityHandler calls this when the agent round-trip ends (phase=end or
        phase=error). ChatHandler uses this to render the fallback bubble when
        no chat final arrived with a message body.

        Architecture: ActivityHandler only tracks state — it never renders.
        ChatHandler makes the render decision via this callback.
        """
        self._lifecycle_completed_callback = cb

    def set_on_agent_start(self, cb):
        """Set callback for agent round start: cb(session_key).

        ActivityHandler calls this when lifecycle phase=start fires. ChatHandler
        uses this to clear the render guard from the previous round so that
        subsequent responses for the same session are not blocked.
        """
        self._on_agent_start_callback = cb

    def set_on_activity_bubble(self, cb: Callable[['ActivityBubble'], None]):
        """Set callback for activity bubbles: cb(activity_bubble).

        ActivityHandler calls this for each tool/plan/approval/command_output/patch
        event to generate a system bubble in the chat. ChatHandler renders via
        build_role_bubble(role='System', text=bubble.format_text()).
        """
        self._activity_bubble_callback = cb

    def set_agent_routing(self, routing_table) -> None:
        """Inject AgentRoutingTable. Called by window.py._build().

        Used by _is_ui_active to resolve project tabs for agent session keys.
        """
        self._agent_to_project = routing_table

    def on_send_initiated(self, session_key: str):
        """Send button pressed — enter pre-flight (sending) state with 30s timeout.

        Resets progress to phase 1 (time-driven). If no res arrives within 30s,
        revert to idle and clear progress.
        """
        sk = self._active_session() or session_key
        self._stop_send_initiated_timer(sk)
        self._reset_progress(sk)
        self._set_state("sending", sk)
        timer_id = self._GLib.timeout_add_seconds(
            self.PREFlight_TIMEOUT_SEC,
            lambda: self._on_preflight_timeout(sk),
        )
        self._send_initiated_timers[sk] = timer_id

    def on_res_confirmed(self, session_key: str):
        """Gateway res confirmed our send — end phase 1, transition to phase 2 (event-driven).

        Called when ChatHandler receives a res matching our pending req_id.
        """
        sk = self._active_session() or session_key
        self._stop_send_initiated_timer(sk)
        # Phase 2: every gateway event now hops the bar
        self._phase[sk] = 2
        self._agent_start_time[sk] = time.monotonic()
        self._set_state("reasoning", sk)

    def on_gateway_event(self, event: str, payload: dict):
        """Universal entry point for all gateway events.

        Every event increments hop count in phase 2 (event-driven). State transitions
        are delegated to specific methods. tick and health have no state handler, so they
        only contribute to progress without causing a state change.
        """
        session_key = payload.get("sessionKey", "") or ""
        sk = self._get_progress_session(session_key)

        # Phase 2: every event hops the bar (skip idle/done — round is over)
        if self._phase.get(sk, 1) == 2 and self._state not in ("idle", "done"):
            self._event_hop_count[sk] = self._event_hop_count.get(sk, 0) + 1
            # TEMPORARILY DISABLED 2026-04-22: Investigating UI freeze on large pastes.
            # Hypothesis: 100+ gateway events during agent response each call
            # _update_feedbar(), queuing too many GLib.idle_add callbacks and
            # starving GTK's render/input loop. If disabling this fixes the freeze,
            # the fix is to throttle _update_feedbar() to e.g. max once per 200ms.
            # TODO: Uncomment the line below once throttling is implemented.
            # self._update_feedbar()

        # ── Bug fix: buffer assistant text for fallback rendering ──────────
        if event == "agent":
            stream = payload.get("stream", "")
            if stream == "assistant":
                text = payload.get("data", {}).get("text", "")
                if text:
                    sk = payload.get("sessionKey", "") or session_key
                    if sk:
                        self._assistant_text_buffer[sk] = text
                        if self._on_assistant_buffer:
                            self._on_assistant_buffer(sk, text)
            if stream == "lifecycle":
                phase = payload.get("data", {}).get("phase", "")
                # Track lifecycle end for missing-message recovery.
                # Cleanup runs on both end and error — fixes memory leak.
                if phase in ("end", "error"):
                    run_id = payload.get("runId", "") or ""
                    sk = payload.get("sessionKey", "") or session_key
                    # Fire lifecycle-completed callback so ChatHandler can render fallback.
                    # text is the last buffered assistant text for this session.
                    if sk and self._lifecycle_completed_callback:
                        text = self._assistant_text_buffer.get(sk, "")
                        self._lifecycle_completed_callback(sk, text)
                    if sk:
                        self._assistant_text_buffer.pop(sk, None)
                    if run_id:
                        self._lifecycle_ended.pop(run_id, None)
                elif phase == "start":
                    # ── Activity bubble: lifecycle start ──────────────────
                    sk = payload.get("sessionKey", "") or session_key
                    if sk and self._activity_bubble_callback:
                        from models.activity import ActivityBubble, ToolStatus
                        bubble = ActivityBubble(type="lifecycle_start", session_key=sk, icon="⏳")
                        self._activity_bubble_callback(bubble)
            elif stream == "item":
                # ── Activity bubble: item events (tool/command/patch) ────────
                # NOTE: stream="tool" events are NOT broadcast to clients — only sent to
                # toolEventRecipients. But stream="item" events ARE broadcast and carry
                # kind="tool" / kind="command" / kind="patch" with phase, name, title, status.
                # This is why exec bubbles worked (command_output is also broadcast) but
                # tool_start/tool_end never appeared (stream="tool" never reaches us).
                data = payload.get("data", {})
                kind = data.get("kind", "")
                item_phase = data.get("phase", "")
                item_name = data.get("name", "") or ""
                item_status = data.get("status", "")
                started_at = data.get("startedAt")
                ended_at = data.get("endedAt")
                sk = payload.get("sessionKey", "") or session_key

                if kind == "tool" and self._activity_bubble_callback:
                    from models.activity import ActivityBubble, ToolStatus
                    if item_phase == "start":
                        self._activity_bubble_callback(
                            ActivityBubble(type="tool_start", session_key=sk, tool_name=item_name,
                                           icon="🔧", status=ToolStatus.RUNNING)
                        )
                    elif item_phase == "end":
                        is_error = item_status == "failed"
                        icon = "❌" if is_error else "✅"
                        btype = "tool_error" if is_error else "tool_end"
                        duration_ms = 0
                        if started_at and ended_at:
                            duration_ms = ended_at - started_at
                        self._activity_bubble_callback(
                            ActivityBubble(type=btype, session_key=sk, tool_name=item_name,
                                           duration_ms=duration_ms, icon=icon,
                                           status=ToolStatus.ERROR if is_error else ToolStatus.SUCCESS)
                        )
            elif stream == "plan":
                # ── Activity bubble: plan update ───────────────────────────
                data = payload.get("data", {})
                title = data.get("title", "") or ""
                steps_raw = data.get("steps", []) or []
                steps = [s.get("title", "") or str(s) for s in steps_raw]
                sk = payload.get("sessionKey", "") or session_key
                if title and self._activity_bubble_callback:
                    from models.activity import ActivityBubble, ToolStatus
                    bubble = ActivityBubble(type="plan", session_key=sk, icon="📋", title=title, steps=steps)
                    self._activity_bubble_callback(bubble)
            elif stream == "approval":
                # ── Activity bubble: approval request ─────────────────────
                data = payload.get("data", {})
                if data.get("phase") == "requested":
                    cmd = data.get("command", "") or ""
                    reason = data.get("reason", "") or ""
                    approval_id = data.get("approvalId", "") or ""
                    sk = payload.get("sessionKey", "") or session_key
                    if cmd and self._activity_bubble_callback:
                        from models.activity import ActivityBubble, ToolStatus
                        bubble = ActivityBubble(type="approval_request", session_key=sk, icon="🔒", command=cmd, reason=reason, approval_id=approval_id)
                        self._activity_bubble_callback(bubble)
            elif stream == "command_output":
                # ── Activity bubble: shell command output ──────────────────
                data = payload.get("data", {})
                if data.get("phase") == "end":
                    name = data.get("name", "") or ""
                    exit_code = data.get("exitCode", 0)
                    duration_ms = data.get("durationMs", 0)
                    sk = payload.get("sessionKey", "") or session_key
                    if name and self._activity_bubble_callback:
                        from models.activity import ActivityBubble, ToolStatus
                        bubble = ActivityBubble(type="command_output", session_key=sk, tool_name=name, exit_code=exit_code, duration_ms=duration_ms, icon="💻")
                        self._activity_bubble_callback(bubble)
            elif stream == "patch":
                # ── Activity bubble: file edit summary ────────────────────
                data = payload.get("data", {})
                if data.get("phase") == "end":
                    name = data.get("name", "") or ""
                    added = len(data.get("added", []) or [])
                    modified = len(data.get("modified", []) or [])
                    deleted = len(data.get("deleted", []) or [])
                    sk = payload.get("sessionKey", "") or session_key
                    if name and self._activity_bubble_callback:
                        from models.activity import ActivityBubble, ToolStatus
                        bubble = ActivityBubble(type="patch", session_key=sk, tool_name=name, added=added, modified=modified, deleted=deleted, icon="✏️")
                        self._activity_bubble_callback(bubble)
        if event == "agent":
            # BUG FIX: lifecycle events (stream="lifecycle") nest phase in data.phase.
            # Item-level events (stream="item") put phase directly in payload.phase.
            stream = payload.get("stream", "")
            if stream == "lifecycle":
                phase = payload.get("data", {}).get("phase", "")
            else:
                phase = payload.get("phase", "")
            if phase == "start":
                self.on_agent_start(session_key, payload)
            elif phase == "end":
                self.on_agent_end(session_key, payload)
            elif phase == "error":
                self.on_agent_error(session_key)

        elif event == "chat":
            state = payload.get("state", "")
            if state == "delta":
                self.on_chat_delta(payload.get("text", "") or "", session_key)
            elif state == "final":
                self.on_chat_final(session_key)

        elif event == "tool_call":
            self.on_tool_use(payload.get("tool_name", "") or "", session_key, payload)

        elif event == "res":
            self.on_res_confirmed(session_key)

        # tick, health, presence, etc. — no state handler, progress only

    # ── Per-session progress helpers ───────────────────────────────────────

    def _get_progress_session(self, session_key: str | None) -> str:
        """Return the session key to use for progress tracking (active session or provided)."""
        return self._active_session() or session_key or "_global_"

    def _reset_progress(self, sk: str):
        """Reset progress state for a session — called on send_initiated."""
        self._progress_start_time[sk] = time.monotonic()
        self._phase[sk] = 1
        self._event_hop_count[sk] = 0

    def _reset_session_state(self, sk: str):
        """Clean up all progress state for a session (on idle/error)."""
        self._progress_start_time.pop(sk, None)
        self._phase.pop(sk, None)
        self._event_hop_count.pop(sk, None)
        self._agent_start_time.pop(sk, None)

    # ── State machine internals ─────────────────────────────────────────────

    def _active_session(self) -> str | None:
        """Return the currently active UI session_key from MainContent, or None."""
        if self._mc is not None:
            try:
                return self._mc.get_current_session_key()
            except Exception:
                pass
        return None

    def _is_ui_active(self, session_key: str | None) -> bool:
        """True if the given session_key matches the currently active UI session.

        Used to guard state transitions — if the UI is showing a different tab
        than the one this event belongs to, we skip the update (deadcode pattern).

        When the active tab is a project tab and the event belongs to an agent
        that is a member of that project, we resolve the agent key to the project
        tab key so the state transition is not incorrectly skipped.
        """
        if session_key is None:
            return True
        active = self._active_session()
        if active is None or session_key == active:
            return True
        # Resolve project tab for agent key — if the active tab is the project
        # tab for this agent, consider it active.
        if self._agent_to_project is not None:
            project_name = self._agent_to_project.get_project(session_key)
            if project_name is not None and f"project:{project_name}" == active:
                return True
        return False

    def _set_state(self, state: str, session_key: str | None):
        """Transition to a new state, cleaning up old timers and starting new ones."""
        # Guard: ignore events for sessions not currently displayed in UI
        if not self._is_ui_active(session_key):
            return

        if state == self._state:
            # Even if already in this state, still update the feedbar for live counters
            if state in ("reasoning", "streaming", "tool_use"):
                self._update_feedbar()
            return

        self._state = state

        # Clean up all timers from previous state
        self._stop_live_update()
        self._stop_idle_pulse()
        if session_key is not None:
            self._stop_done_flash(session_key)
            self._stop_send_initiated_timer(session_key)
        else:
            self._stop_done_flash()
            self._stop_send_initiated_timer()

        # Apply state to FeedBar
        self._update_feedbar()

        # Start timers for new state
        if state in ("reasoning", "streaming", "tool_use"):
            self._live_update_timer = self._GLib.timeout_add(200, self._live_update)
        elif state == "idle":
            self._start_idle_pulse()
        # done: flash timer started by caller

    def _update_feedbar(self):
        """Update FeedBar label + progress bar to reflect current state."""
        state = self._state

        # Build status label markup
        if state == "idle":
            text = '<span foreground="#4ade80">● Idle</span>'
            self._feedbar.set_progress_hidden(True)

        elif state == "sending":
            text = '<span foreground="#f59e0b">⬡ Pre Flight Check</span>'
            self._feedbar.set_progress_fraction(self._compute_progress_fraction())

        elif state == "reasoning":
            text = '<span foreground="#f59e0b">◉ Reasoning…</span>'
            self._feedbar.set_progress_fraction(self._compute_progress_fraction())

        elif state == "streaming":
            text = self._streaming_label()
            self._feedbar.set_progress_fraction(self._compute_progress_fraction())

        elif state == "tool_use":
            tool = self._escape_markup(self._current_tool_name)
            text = f'<span foreground="#a855f7">⚙ {tool}</span>'
            self._feedbar.set_progress_fraction(self._compute_progress_fraction())

        elif state == "done":
            text = '<span foreground="#4ade80">✓ Done</span>'
            self._feedbar.set_progress_fraction(1.0)

        self._feedbar.set_status_text(text)

    def _streaming_label(self) -> str:
        """Build live counter label for streaming state."""
        sk = self._active_session()
        token_est = self._streaming_token_count // 4
        start = self._agent_start_time.get(sk) if sk else None
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

    @staticmethod
    def _escape_markup(text: str) -> str:
        """Escape text for Pango markup."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _compute_progress_fraction(self) -> float:
        """Two-phase progress: phase 1 time-driven (0→85%), phase 2 event-driven (hops→85%).

        Phase 1 (pre-flight, no res yet):
          bar crawls from 0 toward 85% over 60 seconds based on elapsed time.
        Phase 2 (res confirmed, gateway responding):
          every gateway event adds ~2%, capped at 85%.
        """
        sk = self._get_progress_session(None)
        phase = self._phase.get(sk, 1)

        if phase == 1:
            # Time-driven: 0 → 85% over 60 seconds
            start = self._progress_start_time.get(sk)
            if start is None:
                return 0.0
            elapsed = time.monotonic() - start
            return min(elapsed / 60.0, 0.85)
        else:
            # Event-driven: 5% + 2% per hop, capped at 85%
            hops = self._event_hop_count.get(sk, 0)
            return min(0.05 + hops * 0.02, 0.85)

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
        self._idle_pulse_timer = self._GLib.timeout_add(200, self._idle_pulse)

    def _idle_pulse(self):
        """Tick for idle pulse — pulse the progress bar."""
        if self._state != "idle":
            return False
        self._feedbar.pulse_progress()
        return True

    def _start_done_flash(self, session_key: str | None):
        """Start 5-second done→idle flash timer for the given session."""
        sk = session_key
        if sk is None:
            return

        def expire(s: str):
            # Remove from dict first
            self._done_flash_timers.pop(s, None)
            # Only transition if still in done and UI is on this session
            if self._state == "done" and self._is_ui_active(s):
                self._set_state("idle", s)
            return False

        timer_id = self._GLib.timeout_add_seconds(5, lambda: expire(sk))
        self._done_flash_timers[sk] = timer_id

    def _on_preflight_timeout(self, session_key: str):
        """Called when 30s pre-flight timeout expires — revert to idle and clear progress."""
        self._send_initiated_timers.pop(session_key, None)
        if self._state == "sending" and self._is_ui_active(session_key):
            sk = self._active_session() or session_key
            self._reset_session_state(sk)
            self._set_state("idle", session_key)
        return False  # don't re-run

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

    def _stop_done_flash(self, session_key: str | None = None):
        """Stop the done flash timer for a specific session (or all if None)."""
        if session_key is not None:
            timer_id = self._done_flash_timers.pop(session_key, None)
            if timer_id is not None:
                self._GLib.source_remove(timer_id)
        else:
            for timer_id in self._done_flash_timers.values():
                self._GLib.source_remove(timer_id)
            self._done_flash_timers.clear()

    def _stop_send_initiated_timer(self, session_key: str | None = None):
        """Stop the pre-flight timeout timer for a specific session (or all if None)."""
        if session_key is not None:
            timer_id = self._send_initiated_timers.pop(session_key, None)
            if timer_id is not None:
                self._GLib.source_remove(timer_id)
        else:
            for timer_id in self._send_initiated_timers.values():
                self._GLib.source_remove(timer_id)
            self._send_initiated_timers.clear()
