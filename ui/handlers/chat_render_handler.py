# ui/handlers/chat_render_handler.py
# Chat render handler — coordinates text processing and bubble widget creation.
#
# Ported from deadcode's formatters.py (Phase 1 of Chat Formatting Port).
# Security: No secrets, no file I/O, no network calls.
#
# Thread safety: all GTK calls dispatched via GLib.idle_add when GLib is set.
# If GLib is None (tests), GTK calls are made directly — only safe when
# the caller is already on the main thread.
#
# Reentrancy guard: _ReentrancySet prevents concurrent renders for the same
# session_key. If a render is already in-flight for a key, subsequent calls
# are skipped silently. This avoids visual glitches when multiple events
# arrive simultaneously for the same session.
#
# Public API:
#   render(role, text, session_key, on_bubble_ready, on_error=None)
#       Escape + markdown-convert text, build bubble, call on_bubble_ready(widget)
#       on the main thread (via GLib.idle_add when available).
#       session_key enables reentrancy guarding.
#
#   render_sync(role, text, session_key=None) -> Gtk.Widget
#       Synchronous version — only call from the main thread.

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from utils.escaping import escape_for_pango
from utils.markdown import format_markdown
from utils.gtk_safe_link import make_safe_label  # HIGH-6: activate-link guard
from concurrent.futures import ThreadPoolExecutor

from ui.views.chat_bubble import build_role_bubble, process_segments, _clear_crabcards_registry


class _ReentrancySet:
    """
    Tracks which session keys are currently being rendered.

    Prevents concurrent renders for the same session — if a render is
    already in-flight for a key, subsequent calls for that key are skipped.

    Mimics deadcode's _ReentrancySet (chat.py lines 19–33).
    """

    def __init__(self):
        self._keys: set[str] = set()

    def add(self, key: str) -> bool:
        """Add a key. Returns True if not already present (not in flight)."""
        if key in self._keys:
            return False
        self._keys.add(key)
        return True

    def remove(self, key: str):
        """Remove a key when rendering is complete."""
        self._keys.discard(key)

    def __contains__(self, key: str) -> bool:
        return key in self._keys


def _assemble_from_processed(role: str, raw_text: str, processed: list[dict], on_forward_click=None, agent_name: str = None) -> Gtk.Widget:
    """
    Assemble a GTK bubble widget from pre-processed segments.
    Must be called on the main thread — creates GTK widgets.
    """
    from gi.repository import Pango
    from datetime import datetime
    from ui.views.chat_bubble import _build_segment_widget, _build_code_from_markup, _add_action_buttons

    container = Gtk.Box()
    container.set_halign(Gtk.Align.END if role == "You" else Gtk.Align.START)

    bubble = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        css_classes=["chat-bubble-you" if role == "You" else "chat-bubble-agent"],
    )
    bubble.set_margin_top(4)
    bubble.set_margin_bottom(4)

    # Header row
    if agent_name or role == "You":
        timestamp = datetime.now().strftime("%H:%M")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.add_css_class("chat-bubble-header")
        header.set_spacing(4)
        header.set_margin_bottom(2)
        header.set_hexpand(role == "You")
        header.set_halign(Gtk.Align.END if role == "You" else Gtk.Align.START)

        display_name = agent_name if agent_name else "You"
        name_label = Gtk.Label(label=display_name)
        name_label.add_css_class("chat-bubble-header-name")
        name_label.set_halign(Gtk.Align.START)

        dot = Gtk.Box()
        dot.set_size_request(6, 6)
        dot.add_css_class("chat-bubble-header-dot")
        dot.set_valign(Gtk.Align.CENTER)

        time_label = Gtk.Label(label=timestamp)
        time_label.add_css_class("chat-bubble-header-time")
        time_label.set_halign(Gtk.Align.START)

        header.append(name_label)
        header.append(dot)
        header.append(time_label)
        bubble.append(header)

    # Assemble widgets from pre-processed segments
    for pseg in processed:
        seg_type = pseg.get("type", "text")
        if seg_type == "text":
            markup = pseg.get("markup", "")
            if not markup.strip():
                bubble.append(Gtk.Box())
                continue
            # HIGH-6: make_safe_label wires the activate-link scheme guard
            label = make_safe_label(markup, css_class="chat-msg-label")
            bubble.append(label)
        elif seg_type == "code":
            code_markup = pseg.get("code_markup", "")
            lang = pseg.get("lang", "")
            raw_content = pseg.get("raw_content", "")
            block = _build_code_from_markup(lang, code_markup, raw_content)
            if block is not None:
                bubble.append(block)
        else:
            seg_dict = {"type": seg_type, "content": pseg.get("content", "")}
            if "lang" in pseg:
                seg_dict["lang"] = pseg["lang"]
            if "level" in pseg:
                seg_dict["level"] = pseg["level"]
            widget = _build_segment_widget(seg_dict)
            if widget is not None:
                bubble.append(widget)

    # Action buttons
    _add_action_buttons(bubble, raw_text, on_forward_click)

    container.append(bubble)
    return container


class ChatRenderHandler:
    """
    Orchestrates bubble widget creation for chat messages.

    Pipeline (owned by build_role_bubble()):
      1. extract_blocks(raw_text)          — split into typed segments
      2. Per segment:
         - text   → escape_for_pango() + format_markdown()
         - code   → syntax_highlight() (HTML-escapes internally)
         - quote  → escape_for_pango() + format_markdown()
         - heading/task/terminal → escape_for_pango()
      3. Wrap each segment in GTK widgets per CSS classes

    Phase 3 addition: streaming bubbles — text updates live as the agent types.

    Thread safety: render() dispatches GTK calls via GLib.idle_add.
    Use render_sync() only when already on the GTK main thread.

    Reentrancy guard: concurrent renders for the same session_key are skipped.
    This prevents visual glitches when multiple events arrive simultaneously.

    Args:
        GLib_module: gi.repository.GLib or None — for thread-safe GTK calls
    """

    PLAIN_TEXT_THRESHOLD = 2000  # chars — skip fancy formatting above this

    def __init__(self, GLib_module=None):
        self._GLib = GLib_module
        self._reentrancy = _ReentrancySet()
        # Phase 3: streaming bubbles — session_key → (container, label, role, plain_text)
        self._streaming_bubbles: dict = {}
        # Phase 5b: message grouping — tracks last role+session_key for tight spacing
        self._last_message_key: str = None
        self._on_forward_message = None   # set via set_on_forward_message()
        # Phase 5: MainContent reference for self-contained scroll operations
        self._main_content = None
        # Phase 3: Crabcard extraction callback — set via set_on_crabcard_extracted()
        # Called with (list[FeedCardData], session_key) when crabcards are found in a message.
        self._on_crabcard_extracted = None
        # Phase 3: Active project name for crabcard parsing (set via set_project_name())
        self._project_name = ""
        # Streaming throttle: avoid redundant escape+set_markup on every delta
        self._last_stream_update: dict[str, float] = {}  # session_key → monotonic timestamp
        self._stream_throttle_sec = 0.15  # min 150ms between UI updates

    # ── Thread pool for off-main-thread processing ──────────────────
    _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="crabcakes-render")

    # ── Async (thread-safe) ──────────────────────────────────────────────

    def render_async(self, role: str, text: str, session_key: str, on_bubble_ready, on_forward_click=None, on_error=None, agent_name: str = None):
        """
        Process text on a background thread, assemble GTK widgets on main thread.

        Heavy text processing (extract_blocks, escape, markdown, highlight) runs
        on a worker thread. GTK widget assembly is dispatched to the main thread.
        This keeps the UI responsive for large messages.

        Args:
            role:           "You" or "Agent"
            text:           Raw message text
            session_key:    For reentrancy guarding — concurrent renders for same key are skipped
            on_bubble_ready: callback(widget) — called on main thread with finished bubble
            on_forward_click: optional callback for forward button
            on_error:       optional callback(error_msg) — called on main thread
            agent_name:     Optional display name for the agent header
        """
        if not self._reentrancy.add(session_key):
            return  # render already in flight

        # Fast path: skip fancy formatting for large messages
        if len(text) > self.PLAIN_TEXT_THRESHOLD:
            def _plain_on_main():
                try:
                    bubble = self._render_plain_text(
                        role, text,
                        on_forward_click=on_forward_click,
                        agent_name=agent_name,
                    )
                    self._reentrancy.remove(session_key)
                    on_bubble_ready(bubble)
                except Exception as exc:
                    self._reentrancy.remove(session_key)
                    if on_error:
                        on_error(str(exc))
            self._dispatch(_plain_on_main)
            return

        def _process_off_thread():
            try:
                # Heavy pure-Python work — no GTK calls
                processed = process_segments(text)

                def _assemble_on_main():
                    try:
                        bubble = _assemble_from_processed(
                            role, text, processed,
                            on_forward_click=on_forward_click,
                            agent_name=agent_name,
                        )
                        self._reentrancy.remove(session_key)
                        on_bubble_ready(bubble)
                    except Exception as exc:
                        self._reentrancy.remove(session_key)
                        if on_error:
                            on_error(str(exc))

                self._dispatch(_assemble_on_main)
            except Exception as exc:
                self._reentrancy.remove(session_key)
                if on_error:
                    self._dispatch(lambda: on_error(str(exc)))

        self._pool.submit(_process_off_thread)

    def render(self, role: str, text: str, session_key: str, on_bubble_ready, on_forward_click=None, on_error=None):
        """
        Process text and produce a bubble widget asynchronously.

        Args:
            role:           "You" or "Agent"
            text:           Raw message text (no markup assumed)
            session_key:    Session key for reentrancy guarding — if a render is
                           already in-flight for this key, this call is skipped.
            on_bubble_ready: callback(widget) — called on main thread with bubble
            on_error:       optional callback(error_msg) — called on main thread
                           if an exception occurs during processing
        """
        if not self._reentrancy.add(session_key):
            return  # render already in flight for this session_key

        def _build():
            try:
                # Pass raw text — build_role_bubble() owns the full pipeline.
                bubble = build_role_bubble(role, text, on_forward_click=on_forward_click)

                def _deliver():
                    self._reentrancy.remove(session_key)
                    on_bubble_ready(bubble)

                self._dispatch(_deliver)
            except Exception as exc:
                self._reentrancy.remove(session_key)
                if on_error:
                    self._dispatch(lambda: on_error(str(exc)))

        self._dispatch(_build)

    # ── Sync (main thread only) ──────────────────────────────────────────

    def set_on_forward_message(self, cb):
        """Set callback for forward button: cb(text, anchor_widget)."""
        self._on_forward_message = cb

    def set_on_crabcard_extracted(self, cb: "Callable[[list[FeedCardData], str, str], None]") -> None:
        """
        Set callback for when crabcards are extracted from a message.
        Callback: cb(cards: list[FeedCardData], session_key: str, tab_key: str)
        - session_key: agent's gateway key (e.g. "agent:qaster:...")
        - tab_key: key of the chat box where the bubble lives (e.g. "project:crabwatch")
        Called on the same thread as render_sync() — caller should dispatch to main thread if needed.
        """
        self._on_crabcard_extracted = cb

    def set_project_name(self, name: str) -> None:
        """Set the active project name for crabcard parsing."""
        self._project_name = name

    def set_main_content(self, main_content) -> None:
        """Set MainContent reference for self-contained scroll operations and agent name lookup."""
        self._main_content = main_content

    def render_sync(self, role: str, text: str, session_key: str = None, on_forward_click=None, forwarded_from: str = None, agent_name: str = None, tab_key: str = None):
        """
        Process text and return a bubble widget synchronously.

        WARNING: Only call this when already on the GTK main thread.
        For use in signal handlers and idle callbacks.

        Args:
            role:  "You" or "Agent"
            text:  Raw message text
            session_key: Optional session key for reentrancy guarding.
                       If a render is in-flight for this key, returns None.
            tab_key: Optional key for the chat box where the bubble lives.
                     Used for crabcard snapshot lookup. Falls back to session_key.
                     For project chats, this is "project:<name>" while session_key
                     is the agent's gateway key (e.g. "agent:qaster:...").
            agent_name: Optional agent display name. If None and role is "Agent",
                        looked up from _main_content._agent_mgr using session_key.

        Returns:
            Gtk.Widget (a bubble container box), or None if re-entrant.
        """
        if session_key is not None and session_key in self._reentrancy:
            return None
        # Auto-lookup agent name for Agent role if not provided
        if agent_name is None and role == "Agent" and session_key and self._main_content is not None:
            agent_mgr = getattr(self._main_content, '_agent_mgr', None)
            if agent_mgr is not None:
                agent_name = agent_mgr.get_name(session_key)
        current_key = f"{role}:{session_key}" if session_key else None
        tight = (current_key == self._last_message_key) and self._last_message_key is not None

        # Phase 3: Extract crabcard blocks before building bubble
        if self._on_crabcard_extracted is not None and role == "Agent":
            from utils.crabcard_parser import extract_crabcards
            # Clear stale registry entries from previous renders.
            _clear_crabcards_registry()
            # agent_name already resolved above via _agent_mgr.get_name() — use it or default
            agent_for_card = agent_name or "agent"
            cleaned_text, cards = extract_crabcards(text, self._project_name, agent_for_card)
            if cards:
                self._on_crabcard_extracted(cards, session_key or "", tab_key or session_key or "")
        else:
            cleaned_text = text

        bubble = build_role_bubble(role, cleaned_text, on_forward_click=on_forward_click, tight=tight, session_key=session_key, forwarded_from=forwarded_from, agent_name=agent_name)
        self._last_message_key = current_key
        return bubble


    # ── Streaming bubbles (Phase 3) ────────────────────────────────────

    def start_streaming(self, session_key: str, container: Gtk.Box, role: str = "Agent"):
        """
        Start a streaming response bubble in container.

        Creates a pending bubble with a cursor (▍) that text will be appended to.
        If a streaming bubble already exists for session_key, clears it first.

        Args:
            session_key: Session key for this streaming bubble.
            container:   The chat box Gtk.Box to append the bubble to.
            role:        "Agent" or "You" — determines bubble alignment.
        """
        # Clear any existing streaming bubble for this session
        if session_key in self._streaming_bubbles:
            self.end_streaming(session_key)

        from ui.views.chat_bubble import build_streaming_bubble
        bubble, label = build_streaming_bubble(role)

        # Store synchronously so end_streaming can access bubble even before
        # _show runs on the main thread (important when end_streaming is called
        # immediately after start_streaming from the same dispatch chain).
        from models import StreamingBubble
        self._streaming_bubbles[session_key] = StreamingBubble(
            container=container, label=label, role=role, bubble=bubble
        )

        def _show():
            container.append(bubble)

        self._dispatch(_show)

    def is_streaming(self, session_key: str) -> bool:
        """Return True if a streaming bubble exists for session_key."""
        return session_key in self._streaming_bubbles

    def get_streaming_text(self, session_key: str) -> str | None:
        """
        Get the current accumulated plain text for a streaming session.

        Used by AgentRuntimeHandler to extract crabcards from the accumulated
        streaming text before end_streaming() finalizes the bubble.
        Returns None if no streaming bubble exists for this session.
        """
        sb = self._streaming_bubbles.get(session_key)
        return sb.plain_text if sb is not None else None

    def set_streaming_text(self, session_key: str, text: str) -> bool:
        """
        Overwrite the accumulated streaming text for a session.

        Used by AgentRuntimeHandler after extracting crabcards — sets the
        cleaned text so end_streaming() renders the bubble without crabcard blocks.
        Returns True if successful, False if no streaming bubble exists.
        """
        sb = self._streaming_bubbles.get(session_key)
        if sb is None:
            return False
        sb.plain_text = text
        return True

    def update_streaming(self, session_key: str, delta_text: str):
        """
        Update the streaming bubble label for session_key.

        The gateway sends FULL cumulative text in each delta (each delta contains
        all text accumulated so far). Use delta_text directly — do NOT append
        to the stored plain text, as that would double-accumulate.

        Throttled: UI updates are limited to every 150ms to avoid freezing the
        main thread with escape_for_pango + set_markup on every delta. The latest
        text is always stored so the final update is never lost.

        Safe to call from any thread.
        """
        if session_key not in self._streaming_bubbles:
            print(f"[STREAM] update_streaming: SKIP sk={session_key!r} not in _streaming_bubbles")
            return

        sb = self._streaming_bubbles[session_key]

        # Always store latest text (even if throttled) so final render is correct
        sb.plain_text = delta_text

        # Throttle: skip UI update if less than 150ms since last one
        import time
        now = time.monotonic()
        last = self._last_stream_update.get(session_key, 0)
        if now - last < self._stream_throttle_sec:
            return
        self._last_stream_update[session_key] = now

        def _update():
            from utils.escaping import escape_for_pango
            # Use sb.plain_text (always latest) not the delta_text arg
            escaped = escape_for_pango(sb.plain_text)
            sb.label.set_markup(escaped + "<tt>▍</tt>")

        self._dispatch(_update)

    def _render_plain_text(self, role: str, text: str, on_forward_click=None, agent_name: str = None):
        """
        Fast-path bubble for large messages: single Gtk.Label, no fancy formatting.
        Creates the bubble on the main thread — call from _dispatch or directly.

        Follows same container > bubble structure as _assemble_from_processed(),
        but skips extract_blocks/process_segments entirely.
        """
        from gi.repository import Pango
        from datetime import datetime
        from ui.views.chat_bubble import _add_action_buttons

        container = Gtk.Box()
        container.set_halign(Gtk.Align.END if role == "You" else Gtk.Align.START)

        bubble = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            css_classes=["chat-bubble-you" if role == "You" else "chat-bubble-agent"],
        )
        bubble.set_margin_top(4)
        bubble.set_margin_bottom(4)

        # Header (same as _assemble_from_processed)
        if agent_name or role == "You":
            timestamp = datetime.now().strftime("%H:%M")
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            header.add_css_class("chat-bubble-header")
            header.set_spacing(4)
            header.set_margin_bottom(2)
            header.set_hexpand(role == "You")
            header.set_halign(Gtk.Align.END if role == "You" else Gtk.Align.START)

            display_name = agent_name if agent_name else "You"
            name_label = Gtk.Label(label=display_name)
            name_label.add_css_class("chat-bubble-header-name")
            name_label.set_halign(Gtk.Align.START)

            dot = Gtk.Box()
            dot.set_size_request(6, 6)
            dot.add_css_class("chat-bubble-header-dot")
            dot.set_valign(Gtk.Align.CENTER)

            time_label = Gtk.Label(label=timestamp)
            time_label.add_css_class("chat-bubble-header-time")
            time_label.set_halign(Gtk.Align.START)

            header.append(name_label)
            header.append(dot)
            header.append(time_label)
            bubble.append(header)

        # Single plain text label — the fast path
        label = Gtk.Label(label=text)
        label.set_xalign(0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_can_focus(False)
        label.set_selectable(True)
        label.add_css_class("chat-msg-label")
        bubble.append(label)

        # Action buttons (forward, copy)
        _add_action_buttons(bubble, text, on_forward_click)

        container.append(bubble)
        return container

    def end_streaming(self, session_key: str, agent_name: str = None):
        """
        End streaming for session_key: remove cursor and replace with final bubble.

        The streaming bubble is replaced with a proper rendered final bubble.

        Args:
            session_key: The conversation key whose streaming bubble to finalize.
            agent_name: Optional explicit display name (e.g. "Coder", "Debugger")
                to bypass the agent_mgr.get_name() lookup. Pass this when the
                caller (e.g. AgentRuntimeHandler for local special agents) knows
                the display name from the agent registry and the agent is NOT
                in AgentManager. When None, the existing agent_mgr fallback
                runs (which works for gateway agents that ARE registered in
                AgentManager via gateway_handler.on_connected).
        """
        if session_key not in self._streaming_bubbles:
            return

        # Clean up throttle state
        self._last_stream_update.pop(session_key, None)

        sb = self._streaming_bubbles.pop(session_key)

        def _finalize():
            # Use tracked plain text directly (cursor already absent after pop)
            full_text = sb.plain_text

            # Remove streaming bubble widget
            if sb.bubble in sb.container:
                sb.container.remove(sb.bubble)

            # Resolve display name for header. Priority:
            #   1. Explicit agent_name arg (caller knows the name from a
            #      registry AgentManager does not see — used for local
            #      special agents that are NOT in AgentManager).
            #   2. agent_mgr.get_name(session_key) — works for gateway
            #      agents that are registered in AgentManager via
            #      gateway_handler.on_connected().
            #   3. None — build_role_bubble's header condition
            #      `if agent_name or role == "You":` hides the header
            #      when both are falsy. That is the original bug for local
            #      agents; passing agent_name explicitly (priority 1)
            #      prevents the header from being hidden.
            resolved_name = agent_name
            if resolved_name is None and sb.role == "Agent" and self._main_content is not None:
                agent_mgr = getattr(self._main_content, '_agent_mgr', None)
                if agent_mgr is not None:
                    resolved_name = agent_mgr.get_name(session_key)

            # Build and append final bubble
            final_bubble = build_role_bubble(
                sb.role, full_text,
                on_forward_click=self._on_forward_message,
                session_key=session_key,
                agent_name=resolved_name,
            )
            sb.container.append(final_bubble)
            if self._main_content is not None:
                self._main_content.scroll_chat_to_bottom()

        self._dispatch(_finalize)
        # Reset message grouping key so next message starts fresh
        self._last_message_key = None

    def render_event_card(self, event_type: str, container: Gtk.Box, session_key: str = None, **kwargs):
        """
        Render a special event card into container.

        Args:
            event_type: "file_read" | "edit_proposal" | "tool_call" | "error" | "thinking"
            container: Parent box to append the card widget to.
            session_key: Optional session key for agent name lookup (thinking events).
            kwargs: Per-event-type fields:
                file_read:   file_path, snippet="", line_range=""
                edit_proposal: file_path, diff=""
                tool_call:   tool_name, detail=""
                error:       error_msg
                thinking:    thought_text
        """
        from ui.views.chat_bubble import (
            create_file_card,
            create_edit_card,
            create_tool_card,
            create_error_bubble,
        )

        if event_type == "file_read":
            card = create_file_card(kwargs.get("file_path", ""),
                                   kwargs.get("snippet", ""),
                                   kwargs.get("line_range", ""))
        elif event_type == "edit_proposal":
            card = create_edit_card(kwargs.get("file_path", ""),
                                    kwargs.get("diff", ""))
        elif event_type == "tool_call":
            card = create_tool_card(kwargs.get("tool_name", ""),
                                    kwargs.get("detail", ""))
        elif event_type == "error":
            card = create_error_bubble(kwargs.get("error_msg", ""))
        elif event_type == "thinking":
            # Fall back to plain text bubble for thoughts
            text = kwargs.get("thought_text", "")
            # Look up agent name for header
            agent_name = None
            if session_key and self._main_content is not None:
                agent_mgr = getattr(self._main_content, '_agent_mgr', None)
                if agent_mgr is not None:
                    agent_name = agent_mgr.get_name(session_key)
            card = build_role_bubble("Agent", text, agent_name=agent_name)
        elif event_type == "task":
            card = self.render_task_card(
                action=kwargs.get("action", ""),
                task_id=kwargs.get("id", ""),
                title=kwargs.get("title", ""),
                status=kwargs.get("status", ""),
                priority=kwargs.get("priority", ""),
                assigned_to=kwargs.get("assigned_to", ""),
            )
        elif event_type == "diff_summary":
            from ui.views.diff_card import build_diff_summary_card
            parsed_diff = kwargs.get("parsed_diff")
            on_accept_all = kwargs.get("on_accept_all")
            on_reject_all = kwargs.get("on_reject_all")
            card = build_diff_summary_card(
                parsed_diff=parsed_diff,
                on_accept_all=on_accept_all,
                on_reject_all=on_reject_all,
            )
        elif event_type == "diff_file":
            from ui.views.diff_card import build_file_diff_card
            file_diff = kwargs.get("file_diff")
            on_accept_file = kwargs.get("on_accept_file")
            on_reject_file = kwargs.get("on_reject_file")
            card = build_file_diff_card(
                file_diff=file_diff,
                on_accept_file=on_accept_file,
                on_reject_file=on_reject_file,
            )
        elif event_type == "widget":
            # Pass-through for pre-built widgets
            card = kwargs.get("widget")
        else:
            # Unknown event type — ignore silently
            return

        def _append():
            container.append(card)
            if self._main_content is not None:
                self._main_content.scroll_chat_to_bottom()

        self._dispatch(_append)


    def render_task_card(
        self,
        action: str,
        task_id: str,
        title: str,
        status: str,
        priority: str,
        assigned_to: str,
    ) -> Gtk.Widget | None:
        """Render a task card bubble (created/updated)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        # Title label
        title_label = Gtk.Label()
        # MED-9: escape interpolated values to prevent Pango markup injection
        title_label.set_markup(f"<b>Task {action.capitalize()}:</b> {escape_for_pango(task_id)}")
        title_label.set_xalign(0)
        box.append(title_label)

        # Task title
        if title:
            desc_label = Gtk.Label(label=title)
            desc_label.set_xalign(0)
            desc_label.set_selectable(True)
            box.append(desc_label)

        # Status + priority row
        meta_label = Gtk.Label()
        parts = [s for s in [status, priority] if s]
        # MED-9: escape interpolated values to prevent Pango markup injection
        escaped_parts = [escape_for_pango(s) for s in parts if s]
        meta_label.set_markup(" | ".join(escaped_parts))
        meta_label.set_xalign(0)
        box.append(meta_label)

        # Assigned-to
        if assigned_to:
            at_label = Gtk.Label()
            # MED-9: escape interpolated values to prevent Pango markup injection
            at_label.set_markup(f"→ {escape_for_pango(assigned_to)}")
            at_label.set_xalign(0)
            box.append(at_label)

        return box

    def _dispatch(self, fn):
        """Call fn on the GTK main thread."""
        if self._GLib is not None:
            def _wrap():
                fn()
                return False
            self._GLib.idle_add(_wrap)
        else:
            fn()
