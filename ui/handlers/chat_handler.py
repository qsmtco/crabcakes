# ui/handlers/chat_handler.py
# Chat handler — extracted from window.py Phase 1.
#
# Owns: message sending, project fan-out, incoming message routing, tab switching.
# Does NOT own: gateway connection lifecycle, project state, STT, prompt selection.
#
# Thread safety: on_chat_event() is called from the gateway background thread.
# All GTK calls (append_message_to_current_tab, switch_to_session_tab) MUST
# be dispatched via GLib.idle_add(). The handler receives GLib as a constructor
# argument for this purpose.
#
# If GLib is None (e.g. in tests), GTK calls are made directly — only safe
# when the caller is already on the main thread.

from typing import Callable


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
        Handle incoming gateway events. Only "chat" events with state="final"
        are processed — partial transcripts are handled by STT handlers.

        Routing logic:
        - If the sending agent is a known project member, switch to and display
          in the project tab.
        - Otherwise, switch to and display in the agent's own tab.

        Called from: gateway background thread. GTK calls are dispatched via
        GLib.idle_add when available.
        """
        if event != "chat":
            return

        state = payload.get("state", "")
        if state != "final":
            return

        session_key = payload.get("sessionKey", "")
        msg_obj = payload.get("message", {})

        # Extract text from message content — supports str, list of text blocks,
        # or other types (falls back to str() or "")
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
            final_text = "".join(parts)
        elif isinstance(content, str):
            final_text = content
        else:
            final_text = str(content) if content else ""

        if not final_text:
            return

        # Determine which tab to display in: project tab if agent is a project member
        project_name = self._agent_to_project.get(session_key)
        if project_name:
            target_tab = f"project:{project_name}"
        else:
            target_tab = session_key

        # Route to correct tab first, then display — both dispatched to main thread
        self._dispatch(lambda t=target_tab, txt=final_text: (
            self._show_agent_response(t, txt)
        ))

    def _show_agent_response(self, tab, final_text):
        """Render and display an agent response bubble in the correct tab."""
        self.switch_to_tab(tab)
        chat_box = self._mc.get_chat_box()
        if chat_box is not None:
            if self._chat_render_handler is not None:
                bubble = self._chat_render_handler.render_sync("Agent", final_text, tab)
                if bubble is not None:
                    chat_box.append(bubble)
            # Record for test assertions (always called when chat_box supports it)
            if hasattr(chat_box, 'record'):
                chat_box.record("Agent", final_text)

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
