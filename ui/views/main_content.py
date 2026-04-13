# ui/views/main_content.py
# Main content area — right side of the split view
# Contains: notebook (chat tabs), chat control bar, user input + buttons
# Resizable paned divider between top (notebook+bar) and bottom (input+buttons)

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib

from ui.views.chat_control_bar import ChatControlBar
from ui.views.session_menu import show_session_menu

class MainContent(Gtk.Box):
    """
    Main content area widget.
    Vertical split:
      - Top: Gtk.Notebook with chat tabs (one per agent)
      - Bottom: User input box + button bar (scrollable, resizable)
    """

    @property
    def user_input(self):
        """Expose the user_input TextView for external access."""
        return self._user_input

    @property
    def send_button(self):
        """Expose the send button for external signal wiring."""
        return self._send_button

    @property
    def notebook(self):
        """Expose the chat notebook for external tab management."""
        return self._chat_notebook

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # --- TOP: Notebook (with chat scroll overlaid by project settings bar) ---
        top_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self._chat_notebook = Gtk.Notebook()
        self._chat_notebook.set_show_tabs(True)
        self._chat_notebook.set_scrollable(True)
        self._chat_notebook.connect("switch-page", self._on_notebook_switch_page)
        # Track which session_key each tab belongs to.
        # KEY INSIGHT: page_index is NOT stable across tab additions/removals — GTK
        # reuses and shifts indices. Always look up by session_key via _find_page_by_session()
        # or rebuild via _reindex_tabs(). Never capture page_idx in closures.
        self._tab_sessions = {}  # page_index -> session_key
        # Track chat boxes per page_index so we can append to them
        self._tab_chat_boxes = {}  # page_index -> chat_box widget
        self._tab_scrolls = {}   # page_index -> ScrolledWindow widget
        # Phase 5b: scroll-to-bottom button — single floating button overlay on current tab
        self._scroll_to_bottom_btn = None
        self._scroll_to_bottom_overlay = None  # per-tab overlay holding the button
        self._chat_render_handler = None  # injected via set_chat_render_handler()
        # Bulk-close guard: skip reindex until all removals are done
        self._bulk_closing = False

        self._control_bar = ChatControlBar()

        # Top box minimum height — prevents it collapsing when notebook is empty
        top_box.set_size_request(-1, 120)

        top_box.append(self._chat_notebook)
        top_box.append(self._control_bar)

        # ── Project Settings Bar — floating OVER the chat scroll area only ────
        # Placed as overlay on the notebook's chat area (not the tab bar).
        # Semi-transparent; chat content scrolls underneath it.
        # CSS .project-feed-bar provides rgba background + border-radius.
        self._project_settings = Gtk.Box()
        self._project_settings.set_halign(Gtk.Align.FILL)
        self._project_settings.set_valign(Gtk.Align.START)
        self._project_settings.set_size_request(-1, 28)
        self._project_settings.set_margin_top(4)
        self._project_settings.set_margin_bottom(0)
        self._project_settings.add_css_class("project-feed-bar")
        self._project_settings.set_visible(False)  # hidden until a project is opened
        _feed_lbl = Gtk.Label()
        _feed_lbl.set_halign(Gtk.Align.END)
        _feed_lbl.set_margin_start(8)
        _feed_lbl.set_margin_end(8)
        _feed_lbl.set_markup('<span foreground="#6b6b7a" font_desc="Sans 10">Project Settings</span>')
        self._project_settings.append(_feed_lbl)

        # Phase 5b: scroll-to-bottom floating button
        self._scroll_btn = Gtk.Button(label="↓")
        self._scroll_btn.add_css_class("scroll-to-bottom-btn")
        self._scroll_btn.set_opacity(0)  # hidden by default
        self._scroll_btn.connect("clicked", self._on_scroll_to_bottom_clicked)
        self._scroll_btn_box = Gtk.Box()
        self._scroll_btn_box.set_halign(Gtk.Align.END)
        self._scroll_btn_box.set_valign(Gtk.Align.END)
        self._scroll_btn_box.set_hexpand(False)
        self._scroll_btn_box.set_vexpand(False)
        self._scroll_btn_box.append(self._scroll_btn)
        self._scroll_btn_box.set_size_request(48, 36)

        # --- BOTTOM: User input area + button bar ---
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Scrollable text view for typing prompts/commands
        input_scroll = Gtk.ScrolledWindow()
        input_scroll.set_vexpand(True)
        input_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._user_input = Gtk.TextView()
        self._user_input.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._user_input.set_editable(True)
        self._user_input.set_cursor_visible(True)
        self._user_input.set_hexpand(True)
        self._user_input.set_vexpand(True)
        self._user_input.set_left_margin(8)
        self._user_input.set_right_margin(8)
        self._user_input.set_top_margin(6)
        self._user_input.set_bottom_margin(6)
        self._user_input.add_css_class("input-bubble")
        input_scroll.set_child(self._user_input)

        # Button bar — right-justified buttons below the input
        button_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_bar.set_halign(Gtk.Align.END)
        button_bar.set_valign(Gtk.Align.CENTER)
        button_bar.set_size_request(-1, 36)

        self._prompt_button = Gtk.Button(label="Prompt")
        self._prompt_button.add_css_class("flat")
        self._improve_button = Gtk.Button(label="Improve ✦")
        self._improve_button.add_css_class("btn-improve")
        self._send_button = Gtk.Button(label="Send  ↵")
        self._send_button.add_css_class("suggested-action")

        button_bar.set_spacing(6)
        button_bar.append(self._prompt_button)
        button_bar.append(self._improve_button)
        button_bar.append(self._send_button)

        # STT state
        self._on_stt_start_stop = None
        self._on_stt_partial = None
        self._stt_state = "idle"  # "idle" | "recording"

        # Improve state
        self._on_improve_click = None

        # Project tab close callback — set by window via set_on_project_tab_close()
        self._on_project_tab_close = None

        # Agent manager reference — set via set_agent_manager()
        self._agent_mgr = None

        self._prompt_button.connect("clicked", self._on_prompt_clicked)
        self._improve_button.connect("clicked", self._on_improve_clicked)

        bottom_box.append(input_scroll)
        bottom_box.append(button_bar)

        # --- VERTICAL PANED SPLIT ---
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        paned.set_start_child(top_box)
        paned.set_end_child(bottom_box)
        paned.set_resize_start_child(True)
        paned.set_resize_end_child(True)
        paned.set_shrink_start_child(False)
        paned.set_shrink_end_child(False)
        paned.set_position(400)

        self.append(paned)

    def set_project_settings_text(self, text: str):
        """Set text or markup on the project settings bar. Handles Pango markup correctly."""
        for child in list(self._project_settings):
            self._project_settings.remove(child)
        lbl = Gtk.Label()
        lbl.set_halign(Gtk.Align.END)
        lbl.set_margin_start(8)
        lbl.set_margin_end(8)
        if text.startswith("<"):
            lbl.set_markup(text)
        else:
            lbl.set_text(text)
        self._project_settings.append(lbl)

    def set_on_project_settings_update(self, cb):
        """Set callback for project settings updates. cb(project_name, member_count)."""
        self._on_feed_bar_update = cb

    def _update_project_settings_from_project(self, project_name: str, member_count: int):
        """Internal — called by window to refresh the project settings bar."""
        if project_name:
            self._project_settings.set_visible(True)
            self.set_project_settings_text(
                f'<span font_desc="Sans 10"><b>{project_name}</b>  ·  {member_count} member{"s" if member_count != 1 else ""}</span>'
            )
        else:
            self._project_settings.set_visible(False)
            self.set_project_settings_text('Project Settings')

    def set_feed_bar_text(self, text):
        """Update the project feed bar with a status message."""
        for child in list(self._project_settings):
            self._project_settings.remove(child)
        if text:
            lbl = Gtk.Label()
            lbl.set_halign(Gtk.Align.END)
            lbl.set_margin_start(8)
            lbl.set_margin_end(8)
            if text.startswith("<"):
                lbl.set_markup(text)
            else:
                lbl.set_text(text)
            self._project_settings.append(lbl)

    # ── Tab management ──────────────────────────────────────────────────────

    def create_chat_tab(self, session_key, agent_name):
        """
        Create a new chat tab for an agent.
        Returns the page index of the new tab, or existing tab index if already exists.
        """
        # Check if tab already exists for this session_key
        for page_idx, sk in self._tab_sessions.items():
            if sk == session_key:
                self._chat_notebook.set_current_page(page_idx)
                return page_idx

        # Scrollable container for the chat content — wrapped in Overlay so the
        # project settings bar can float over it (below the tab row).
        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.set_vexpand(True)
        chat_scroll.set_hexpand(True)
        chat_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        chat_overlay = Gtk.Overlay()
        chat_overlay.set_vexpand(True)
        chat_overlay.set_child(chat_scroll)
        chat_overlay.add_overlay(self._project_settings)
        # Phase 5b: scroll-to-bottom button on this tab's overlay
        chat_overlay.add_overlay(self._scroll_btn_box)

        # Vertical box for chat messages
        chat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        chat_box.set_halign(Gtk.Align.FILL)
        chat_box.set_valign(Gtk.Align.END)
        chat_scroll.set_child(chat_box)

        # Tab label = agent name + close button
        tab_label_box = Gtk.Box(spacing=4)
        tab_label_box.set_valign(Gtk.Align.CENTER)

        tab_label = Gtk.Label(label=agent_name)
        tab_label.set_valign(Gtk.Align.CENTER)
        tab_label.set_hexpand(True)  # ensure label gets space over button

        close_btn = Gtk.Button(label="×")
        close_btn.set_valign(Gtk.Align.CENTER)
        close_btn.set_has_frame(False)
        close_btn.set_focus_on_click(False)
        close_btn.set_size_request(20, -1)
        close_btn.set_hexpand(False)

        tab_label_box.append(tab_label)
        tab_label_box.append(close_btn)

        # Append the new tab FIRST to get page_idx, then wire handlers
        page_idx = self._chat_notebook.append_page(chat_overlay, tab_label_box)

        # Store session_key on the tab label box so close handlers can look up
        # the CURRENT page index dynamically (avoids stale captured page_idx bug
        # when tabs are closed out of order and reindexing shifts pages).
        tab_label_box._session_key = session_key
        chat_scroll._session_key = session_key

        close_btn.connect("clicked", self._on_tab_close_clicked)

        # Middle-click on the label also closes the tab
        click_ctrl = Gtk.GestureClick()
        click_ctrl.set_button(Gdk.BUTTON_MIDDLE)
        click_ctrl.connect("pressed", self._on_tab_middle_click)
        tab_label_box.add_controller(click_ctrl)

        # Right-click on the label shows session switch menu
        right_ctrl = Gtk.GestureClick()
        right_ctrl.set_button(Gdk.BUTTON_SECONDARY)
        right_ctrl.connect("pressed", self._on_tab_right_click, session_key)
        tab_label_box.add_controller(right_ctrl)
        self._tab_sessions[page_idx] = session_key
        self._tab_chat_boxes[page_idx] = chat_box
        self._tab_scrolls[page_idx] = chat_scroll
        # Phase 5b: wire scroll adjustment callback for scroll-to-bottom button
        vadj = chat_scroll.get_vadjustment()
        if vadj is not None:
            vadj.connect("value-changed", self._on_vadjustment_changed, page_idx)
        self._chat_notebook.set_current_page(page_idx)
        return page_idx

    def _on_notebook_switch_page(self, notebook, _page, page_num):
        """Scroll to bottom when user switches to a tab."""
        self.scroll_chat_to_bottom(page_num)

    def _find_page_by_session(self, session_key):
        """Return the current page index for a session_key by scanning notebook tab labels.

        The _session_key attribute is stored on the tab_label_box (the tab),
        not the page widget. Use get_tab_label() to access it.
        """
        n_pages = self._chat_notebook.get_n_pages()
        for idx in range(n_pages):
            page_widget = self._chat_notebook.get_nth_page(idx)
            tab_label = self._chat_notebook.get_tab_label(page_widget)
            if tab_label and getattr(tab_label, "_session_key", None) == session_key:
                return idx
        return None

    def _close_tab(self, page_idx):
        """Remove a tab by page index and clean up tracking dicts."""
        self._chat_notebook.remove_page(page_idx)
        self._tab_sessions.pop(page_idx, None)
        self._tab_chat_boxes.pop(page_idx, None)
        if not self._bulk_closing:
            self._reindex_tabs()

    def _reindex_tabs(self):
        """
        Rebuild _tab_sessions and _tab_chat_boxes to reflect current notebook page order.

        Correct algorithm: iterate current GTK pages (which are the authoritative order),
        look up each page's widget, then find the matching session_key by scanning
        the saved snapshot. This avoids index-stale issues when multiple tabs are removed.
        """
        # Snapshot current state before rebuilding
        saved_sessions = dict(self._tab_sessions)
        saved_chat_boxes = dict(self._tab_chat_boxes)
        saved_scrolls = dict(self._tab_scrolls)

        # Build widget -> old_page_idx map from snapshot
        widget_to_idx = {}
        for old_idx, sk in saved_sessions.items():
            if old_idx in self._tab_chat_boxes:
                widget_to_idx[self._tab_chat_boxes[old_idx]] = old_idx

        new_sessions = {}
        new_chat_boxes = {}
        new_scrolls = {}
        n_pages = self._chat_notebook.get_n_pages()
        for new_idx in range(n_pages):
            page_widget = self._chat_notebook.get_nth_page(new_idx)
            old_idx = widget_to_idx.get(page_widget)
            if old_idx is not None:
                new_sessions[new_idx] = saved_sessions[old_idx]
                new_chat_boxes[new_idx] = saved_chat_boxes[old_idx]
                new_scrolls[new_idx] = saved_scrolls[old_idx]

        self._tab_sessions = new_sessions
        self._tab_chat_boxes = new_chat_boxes
        self._tab_scrolls = new_scrolls

    def close_tabs(self, page_indices):
        """
        Close multiple tabs in one call, reindexing only once at the end.

        Tabs are closed highest-index-first so that lower indices remain stable
        for the duration of the loop.

        Args:
            page_indices: iterable of int page indices to close
        """
        if not page_indices:
            return
        self._bulk_closing = True
        try:
            for idx in sorted(page_indices, reverse=True):
                self._chat_notebook.remove_page(idx)
                self._tab_sessions.pop(idx, None)
                self._tab_chat_boxes.pop(idx, None)
        finally:
            self._bulk_closing = False
        self._reindex_tabs()

    def _on_tab_close_clicked(self, _btn):
        """× button clicked on a tab — close it. For project tabs, also close the project."""
        tab_label_box = _btn.get_parent()
        session_key = getattr(tab_label_box, "_session_key", None) if tab_label_box else None
        if session_key is None:
            return
        page_idx = self._find_page_by_session(session_key)
        if page_idx is None:
            return
        # If it's a project tab, close the project in left_panel
        if self._on_project_tab_close and session_key.startswith("project:"):
            self._on_project_tab_close(session_key)
        self._close_tab(page_idx)

    def set_on_project_tab_close(self, cb):
        """Set callback for when a project tab is closed. cb(session_key)."""
        self._on_project_tab_close = cb

    def _on_tab_middle_click(self, ctrl, n_press, x, y):
        """Middle-click on tab label — close it."""
        if n_press != 1:
            return
        tab_label_box = ctrl.get_widget()
        session_key = getattr(tab_label_box, "_session_key", None) if tab_label_box else None
        if session_key is None:
            return
        page_idx = self._find_page_by_session(session_key)
        if page_idx is not None:
            self._close_tab(page_idx)

    def _on_tab_right_click(self, ctrl, n_press, x, y, session_key):
        """Right-click on tab label — show session switch menu."""
        if n_press != 1:
            return
        if self._agent_mgr is None:
            return
        agent_name = self._agent_mgr.get_name(session_key)
        if not agent_name:
            return
        sessions = self._agent_mgr.get_sessions(agent_name)
        tab_widget = ctrl.get_widget()
        page_idx = self._find_page_by_session(session_key)
        if page_idx is None:
            return
        show_session_menu(
            tab_widget,
            agent_name,
            sessions,
            lambda sk: self._switch_tab_session(page_idx, sk),
        )

    def _switch_tab_session(self, page_idx, new_session_key):
        """Switch an existing tab to a new session key.

        Note: this only updates _tab_sessions — it does NOT create a new tab,
        switch to it, or change the visible label. The tab keeps showing its
        original agent_name. The session_key used for routing incoming messages
        is what changes. Designed for switching between sessions of the same agent."""
        self._tab_sessions[page_idx] = new_session_key

    def get_current_session_key(self):
        """Return the session_key for the currently active tab, or None."""
        current = self._chat_notebook.get_current_page()
        return self._tab_sessions.get(current)

    def get_chat_box(self, page_index=None):
        """Return the chat box widget for a given page index (default: current page)."""
        if page_index is None:
            page_index = self._chat_notebook.get_current_page()
        return self._tab_chat_boxes.get(page_index)

    def get_chat_box_for_session(self, session_key: str):
        """
        Return the chat box widget for the tab matching session_key.

        Iterates over _tab_sessions to find the page_index with the matching
        session_key, then returns the corresponding chat box.
        Returns None if no tab exists for that session_key.
        """
        for page_idx, sk in self._tab_sessions.items():
            if sk == session_key:
                return self._tab_chat_boxes.get(page_idx)
        return None

    def set_chat_render_handler(self, handler):
        """Inject ChatRenderHandler instance. Called by window.py._build()."""
        self._chat_render_handler = handler

    def scroll_chat_to_bottom(self, page_index=None):
        """Scroll the chat ScrolledWindow to the bottom."""
        if page_index is None:
            page_index = self._chat_notebook.get_current_page()
        scroll = self._tab_scrolls.get(page_index)
        if scroll is None:
            return
        vadj = scroll.get_vadjustment()
        if vadj is None:
            return
        # Defer scroll to next frame — widget layout must recalculate first
        def _do_scroll():
            vadj.set_value(vadj.get_upper() - vadj.get_page_size())
            return False  # don't repeat
        from gi.repository import GLib
        GLib.idle_add(_do_scroll)

    def _on_scroll_to_bottom_clicked(self, *args):
        """Handle scroll-to-bottom button click — scroll current tab to bottom."""
        self.scroll_chat_to_bottom()
        self._scroll_btn.set_opacity(0)

    def _on_vadjustment_changed(self, adjustment, page_index):
        """
        Show scroll-to-bottom button when user scrolls up away from bottom.
        Hide it when user is at or near the bottom of the chat.
        """
        current_page = self._chat_notebook.get_current_page()
        if page_index != current_page:
            return  # only track current page
        upper = adjustment.get_upper()
        page_size = adjustment.get_page_size()
        current_value = adjustment.get_value()
        # distance_from_bottom: how far the scroll is from the bottom
        distance_from_bottom = upper - page_size - current_value
        if distance_from_bottom > 80:
            self._scroll_btn.set_opacity(1)
        else:
            self._scroll_btn.set_opacity(0)

    # ── STT (Speech-to-Text) ───────────────────────────────────────────────
    # State machine: idle → click → recording → click → idle.
    # update_stt_state() drives the button label/style.
    # append_stt_text() appends partial transcripts as they arrive.

    def set_on_stt_click(self, cb):
        """Set callback for when the Prompt (STT) button is clicked."""
        self._on_stt_start_stop = cb

    def set_on_stt_partial(self, cb):
        """Set callback for partial STT results — append to input buffer."""
        self._on_stt_partial = cb

    def update_stt_state(self, state):
        """
        Update the Prompt button appearance to reflect STT state.
        state: "idle" | "recording"
        """
        self._stt_state = state
        if state == "recording":
            self._prompt_button.set_label("■ Stop")
            self._prompt_button.add_css_class("destructive-action")
        else:
            self._prompt_button.set_label("Prompt")
            self._prompt_button.remove_css_class("destructive-action")

    def append_stt_text(self, text):
        """
        Insert STT transcript text at the current cursor position in the input buffer.
        If text is selected, it is replaced. Cursor ends up after the inserted text.
        """
        buf = self.user_input.get_buffer()
        buf.insert_at_cursor(text)
        self.user_input.grab_focus()

    def set_agent_manager(self, agent_mgr):
        """Set the AgentManager for session lookup (used by session switch menu)."""
        self._agent_mgr = agent_mgr

    def _on_prompt_clicked(self, *args):
        """Forward button click to the registered STT callback."""
        if self._on_stt_start_stop:
            self._on_stt_start_stop()

    def set_on_improve_click(self, cb):
        """Set callback for when the Improve button is clicked."""
        self._on_improve_click = cb

    def _on_improve_clicked(self, *args):
        """Forward button click to the registered improve callback."""
        if self._on_improve_click:
            self._on_improve_click()

    def replace_input_text(self, text):
        """Replace the entire input buffer with improved text."""
        buf = self.user_input.get_buffer()
        buf.set_text(text)
        end_iter = buf.get_end_iter()
        buf.place_cursor(end_iter)
        self.user_input.grab_focus()
