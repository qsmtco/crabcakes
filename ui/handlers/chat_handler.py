# ui/handlers/chat_handler.py
# Chat handler — extracted from window.py Phase 1.
#
# Owns: message sending, project fan-out, incoming message routing, tab switching.
# Does NOT own: gateway connection lifecycle, project state, STT, prompt selection.
#
# Thread safety: on_chat_event() is called from the gateway background thread.
# All GTK calls (switch_to_tab, get_chat_box) MUST
# be dispatched via GLib.idle_add(). The handler receives GLib as a constructor
# argument for this purpose.
#
# If GLib is None (e.g. in tests), GTK calls are made directly — only safe
# when the caller is already on the main thread.

from typing import Callable

# ── Feature flags ──────────────────────────────────────────────────────────────
STREAMING_ENABLED = False  # True = show live updates as agent types; False = final only
# ──────────────────────────────────────────────────────────────────────────────


class ChatHandler:
    """
    Handles all chat-related logic: sending, fan-out, and routing responses.

    This handler is thread-aware: its public methods may be called from
    background threads (gateway client thread). GTK operations are dispatched
    via GLib.idle_add when a GLib module is provided.

    Args:
        main_content:       MainContent instance — for tab ops and input access
        gateway_client:     GatewayClient instance — for send_message()
        agent_to_project:   dict — maps session_key → project_name (read-only ref)
        projects_module:    utils.projects module — for load_members()
        GLib_module:        gi.repository.GLib or None — for thread-safe GTK calls
    """

    def __init__(
        self,
        main_content,      # MainContent
        gateway_client,    # GatewayClient
        agent_to_project: dict,
        projects_module,   # module — utils.projects
        GLib_module=None,  # gi.repository.GLib or None
    ):
        self._mc = main_content
        self._gw = gateway_client
        # agent_to_project is a read-only reference — window owns and updates it
        self._agent_to_project = agent_to_project
        self._projects = projects_module
        self._GLib = GLib_module
        self._chat_render_handler = None  # injected via set_chat_render_handler()

    def set_chat_render_handler(self, handler):
        """Inject ChatRenderHandler. Called by window.py._build()."""
        self._chat_render_handler = handler

    # ── Public API ───────────────────────────────────────────────────────────

    def set_gateway_client(self, gw):
        """
        Set or replace the live GatewayClient reference.
        Called by GatewayHandler after successful connect.
        Window no longer needs to reach into _gw directly.
        """
        self._gw = gw

    def on_send_clicked(self, _btn=None):
        """GTK signal handler for the Send button. Delegates to on_send."""
        self.on_send()

    def on_send(self):
        """
        Read input text, display it in the current tab, send it to the gateway.

        If the current tab is a project tab ("project:<name>"), fan-out to all
        project members. Otherwise send directly to the single agent session.
        """
        if self._gw is None or not self._gw.is_connected():
            return

        session_key = self._mc.get_current_session_key()
        if session_key is None:
            return

        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()
        if not text:
            return

        # Display bubble AND send message (both happen in same dispatch)
        def _show_and_send():
            chat_box = self._mc.get_chat_box()
            if chat_box is not None:
                if self._chat_render_handler is not None:
                    bubble = self._chat_render_handler.render_sync("You", text, session_key)
                    if bubble is not None:
                        chat_box.append(bubble)
                self._mc.scroll_chat_to_bottom()
                # Record for test assertions (FakeChatBox.record also called by append if supported)
                if hasattr(chat_box, 'record'):
                    chat_box.record("You", text)
            if session_key.startswith("project:"):
                project_name = session_key.split(":", 1)[1]
                members = self._projects.load_members(project_name)
                for member in members:
                    self._gw.send_message(member, text)
            else:
                self._gw.send_message(session_key, text)
        self._dispatch(_show_and_send)
        buf.set_text("")

    def on_chat_event(self, event: str, payload: dict):
        """
        Handle incoming gateway events.

        Event types:
          - "chat" (delta)   → update streaming bubble
          - "chat" (final)   → end streaming + render final bubble
          - Other events      → ignored

        Routing logic (for chat events):
        - If the sending agent is a known project member, switch to and display
          in the project tab.
        - Otherwise, switch to and display in the agent's own tab.

        Called from: gateway background thread. GTK calls are dispatched via
        GLib.idle_add when available.
        """
        session_key = payload.get("sessionKey", "") or ""
        project_name = self._agent_to_project.get(session_key)
        target_tab = f"project:{project_name}" if project_name else session_key

        if event != "chat":
            # Handle Phase 4 special event cards
            special_events = ("file_read", "edit_proposal", "tool_call", "error", "thinking")
            if event in special_events:
                self._dispatch(lambda e=event, sk=session_key, tt=target_tab, pl=payload: (
                    self._handle_special_event(e, sk, tt, pl)
                ))
            return

        state = payload.get("state", "")
        msg_obj = payload.get("message", {})

        if state == "delta":
            delta_text = self._extract_text(msg_obj)
            if not delta_text:
                return
            self._dispatch(lambda sk=session_key, tt=target_tab, txt=delta_text: (
                self._handle_streaming_delta(sk, tt, txt)
            ))
        elif state == "final":
            final_text = self._extract_text(msg_obj)
            if not final_text:
                return
            # session_key: bubble teardown key; target_tab: UI switch + chat box
            self._dispatch(lambda t=target_tab, sk=session_key, txt=final_text: (
                self._handle_final_response(t, sk, txt)
            ))

    def _handle_streaming_delta(self, session_key: str, target_tab: str, delta_text: str):
        """
        Update the streaming bubble for session_key with the latest delta text.

        Controlled by STREAMING_ENABLED. When disabled, delta events are ignored
        and the message appears only when the final event arrives.
        """
        if not STREAMING_ENABLED:
            return  # streaming disabled — wait for final event
        if self._chat_render_handler is None:
            return
        if not self._chat_render_handler.is_streaming(session_key):
            chat_box = self._mc.get_chat_box_for_session(target_tab)
            if chat_box is not None:
                self._chat_render_handler.start_streaming(session_key, chat_box, "Agent")
        self._chat_render_handler.update_streaming(session_key, delta_text)

    def _handle_final_response(self, tab: str, session_key: str, final_text: str):
        """
        End any streaming bubble (if one exists) and record the message.

        When STREAMING_ENABLED is False, no streaming bubble is ever started,
        so end_streaming() is a no-op. In that case we fall back to render_sync()
        to create the final bubble directly.
        """
        self.switch_to_tab(tab)
        chat_box = self._mc.get_chat_box()
        if hasattr(chat_box, 'record'):
            chat_box.record("Agent", final_text)
        if self._chat_render_handler is None:
            return
        if self._chat_render_handler.is_streaming(session_key):
            self._chat_render_handler.end_streaming(session_key)
        else:
            # No streaming bubble existed (STREAMING_ENABLED=False or first msg):
            # render the final bubble via render_sync instead.
            bubble = self._chat_render_handler.render_sync("Agent", final_text, session_key)
            if bubble is not None and chat_box is not None:
                chat_box.append(bubble)
                self._mc.scroll_chat_to_bottom()

    def _extract_text(self, msg_obj) -> str:
        """Extract plain text from a message object."""
        if isinstance(msg_obj, dict):
            content = msg_obj.get("content", "")
        else:
            content = msg_obj
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text", "")
                    if t:
                        parts.append(t)
            return "".join(parts)
        elif isinstance(content, str):
            return content
        return str(content) if content else ""

    def _show_agent_response(self, tab, final_text):
        """Render and display an agent response bubble in the correct tab."""
        self.switch_to_tab(tab)
        chat_box = self._mc.get_chat_box()
        if chat_box is not None:
            if self._chat_render_handler is not None:
                bubble = self._chat_render_handler.render_sync("Agent", final_text, tab)
                if bubble is not None:
                    chat_box.append(bubble)
            self._mc.scroll_chat_to_bottom()
            # Record for test assertions (always called when chat_box supports it)
            if hasattr(chat_box, 'record'):
                chat_box.record("Agent", final_text)

    def _handle_special_event(self, event_type: str, session_key: str, target_tab: str, payload: dict):
        """
        Render a special event card (Phase 4: file_read, edit_proposal, tool_call, error, thinking).

        Args:
            event_type: Event name from gateway (e.g. "file_read")
            session_key: Session key for the agent/project tab
            target_tab:  Tab name for UI switching
            payload:     Full event payload dict
        """
        self.switch_to_tab(target_tab)
        chat_box = self._mc.get_chat_box_for_session(target_tab)
        if chat_box is None or self._chat_render_handler is None:
            return

        msg_obj = payload.get("message", {})

        if event_type == "file_read":
            self._chat_render_handler.render_event_card(
                "file_read", chat_box,
                file_path=msg_obj.get("file_path", "<unknown file>"),
                snippet=msg_obj.get("snippet", ""),
                line_range=msg_obj.get("line_range", ""),
            )
        elif event_type == "edit_proposal":
            self._chat_render_handler.render_event_card(
                "edit_proposal", chat_box,
                file_path=msg_obj.get("file_path", "<unknown file>"),
                diff=msg_obj.get("diff", ""),
            )
        elif event_type == "tool_call":
            self._chat_render_handler.render_event_card(
                "tool_call", chat_box,
                tool_name=msg_obj.get("tool_name", "<unknown tool>"),
                detail=msg_obj.get("detail", ""),
            )
        elif event_type == "error":
            self._chat_render_handler.render_event_card(
                "error", chat_box,
                error_msg=msg_obj.get("error_msg", msg_obj.get("content", "Unknown error")),
            )
        elif event_type == "thinking":
            self._chat_render_handler.render_event_card(
                "thinking", chat_box,
                thought_text=msg_obj.get("thought_text", msg_obj.get("content", "")),
            )
        self._mc.scroll_chat_to_bottom()

    def switch_to_tab(self, session_key: str):
        """
        Switch the chat notebook to the tab matching session_key.
        No-op if no matching tab exists.
        """
        notebook = self._mc.notebook
        for page_idx in range(notebook.get_n_pages()):
            if self._mc._tab_sessions.get(page_idx) == session_key:
                notebook.set_current_page(page_idx)
                break

    # ── Internal ─────────────────────────────────────────────────────────────

    def _dispatch(self, fn: Callable):
        """Call fn on the GTK main thread. Direct call if GLib not available."""
        if self._GLib is not None:
            def _wrap():
                fn()
                return False  # remove idle source after one execution
            self._GLib.idle_add(_wrap)
        else:
            fn()
