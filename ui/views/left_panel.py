# ui/views/left_panel.py
# Left sidebar panel — contains the Prompts/Agents/Projects notebook (PAP)

import gi
# Require GTK 4.0 — must be called before importing Gtk
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from utils.prompts import load_prompts
from utils.projects import load_members, save_members
from utils.icons import render_agent_icon
from ui.views.file_tree import FileTree


class LeftPanel(Gtk.Box):
    """
    Left sidebar panel widget.
    Contains a Gtk.Notebook with three tabs: Prompts, Agents, Projects.
    """

    def __init__(self, on_prompt_selected=None, on_project_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # Prompt callback
        self._on_prompt_selected = on_prompt_selected

        # Project callback
        self._on_project_selected = on_project_selected

        # Agent state — set via set_agents() after gateway connects
        self._agent_names = {}
        self._on_agent_selected = None
        self._agents_list_box = None
        self._agent_list_handler = None  # set via set_agent_list_handler()

        # Project state — set via set_on_project_opened() when a project tab opens
        self._active_project_name = None
        self._on_project_opened = None
        self._on_project_members_changed = None

        # Create the notebook (tabbed interface)
        PAP_notebook = Gtk.Notebook()

        # Tab 1: Prompts
        prompts_list = self._build_prompts_list()
        PAP_notebook.append_page(
            prompts_list,
            Gtk.Label(label="Prompts")
        )

        # Tab 2: Agents — placeholder until set_agents() is called
        agents_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        agents_container.set_vexpand(True)
        self._agents_placeholder = Gtk.Label()
        self._agents_placeholder.set_markup(
            '<span foreground="#6b6b7a" font_desc="Sans 11">'
            'Click Connect to discover agents</span>')
        self._agents_placeholder.set_halign(Gtk.Align.CENTER)
        self._agents_placeholder.set_valign(Gtk.Align.CENTER)
        agents_container.append(self._agents_placeholder)
        PAP_notebook.append_page(
            agents_container,
            Gtk.Label(label="Agents")
        )

        # Tab 3: Projects — FileTree with expandable directory browser
        self._file_tree = FileTree(on_file_selected=self._on_project_selected)
        PAP_notebook.append_page(
            self._file_tree,
            Gtk.Label(label="Projects")
        )

        self.append(PAP_notebook)

    # ── Agents tab ──────────────────────────────────────────────────────────

    def set_agent_list_handler(self, handler):
        """Set the AgentListHandler for avatar card rendering."""
        self._agent_list_handler = handler
        # If agent names are already populated, refresh now that handler has agent_mgr
        if self._agent_names:
            self._refresh_agents_list()

    def set_agents(self, agent_names, on_agent_selected):
        """
        Populate the agents tab and register the selection callback.
        Called by window after gateway connects and agents are discovered.
        """
        self._agent_names = agent_names
        self._on_agent_selected = on_agent_selected
        self._refresh_agents_list()

    def set_on_project_opened(self, cb):
        """Set callback for when a project tab is opened."""
        self._on_project_opened = cb

    def set_on_project_members_changed(self, cb):
        """Set callback for when project membership changes."""
        self._on_project_members_changed = cb

    def refresh_agents_with_project(self, project_name):
        """Called by window when a project tab opens — refreshes +/− buttons."""
        self._active_project_name = project_name
        self._refresh_agents_list()

    def _refresh_agents_list(self):
        """
        Rebuild the agents tab content from current _agent_names.
        Called on initial population and on subsequent refreshes.
        """
        # Find the agents tab page (index 1)
        notebook = self.get_first_child()
        if notebook is None:
            return

        agents_page_idx = 1
        agents_page = notebook.get_nth_page(agents_page_idx)
        if agents_page is None:
            return

        # Find the scroll container inside agents_page (may be placeholder or old scroll)
        scroll = agents_page.get_first_child()

        # If first child is not a scroll (it's the placeholder label), clear the container
        if scroll is not None and not isinstance(scroll, Gtk.ScrolledWindow):
            scroll.unparent()
            scroll = None

        # If no scroll yet, create one
        if scroll is None:
            scroll = Gtk.ScrolledWindow()
            scroll.set_vexpand(True)
            scroll.set_hexpand(True)
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            agents_page.append(scroll)

        # Remove existing list_box from scroll — GTK4 set_child() auto-unparents old child

        # List box for agent rows
        self._agents_list_box = Gtk.ListBox()
        self._agents_list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)

        # Load project members if a project is active
        project_members = []
        if self._active_project_name:
            project_members = load_members(self._active_project_name)

        # Use handler only if it has a populated agent_mgr, otherwise fall back to _agent_names
        # This matters on first connect: set_agents() fires before set_agent_mgr()
        if self._agent_list_handler and self._agent_list_handler.has_agent_mgr():
            sorted_agents = self._agent_list_handler.get_sorted_agents(project_members)
        else:
            # Fallback: group by name, prefer :main (old behavior)
            agents = {}
            for session_key, name in self._agent_names.items():
                if name not in agents:
                    agents[name] = session_key
                if ":main" in session_key:
                    agents[name] = session_key
            sorted_agents = [(sk, name, sk in project_members) for name, sk in agents.items()]

        if not sorted_agents:
            placeholder = Gtk.Label()
            placeholder.set_markup(
                '<span foreground="#6b6b7a" font_desc="Sans 11">'
                'No agents found</span>')
            placeholder.set_halign(Gtk.Align.CENTER)
            placeholder.set_valign(Gtk.Align.CENTER)
            placeholder.show()
            self._agents_list_box.append(placeholder)
        else:
            for session_key, name, in_project in sorted_agents:
                row = self._build_agent_row(session_key, name, in_project)
                self._agents_list_box.append(row)

        # Single-click activates (opens chat tab)
        self._agents_list_box.set_activate_on_single_click(False)
        self._agents_list_box.connect("row_activated", self._on_agent_row_activated)

        scroll.set_child(self._agents_list_box)
        self._agents_list_box.show()

    def _build_agent_row(self, session_key, name, in_project=False):
        """
        Build a single agent avatar card row.

        Layout: [avatar] [name label] [+/−] [Chat]
        Avatar uses render_agent_icon via the agent_list_handler (if set).
        """
        row = Gtk.ListBoxRow()
        row._session_key = session_key
        row._agent_name = name

        # Get initials and color from handler (or compute defaults)
        if self._agent_list_handler:
            initials = self._agent_list_handler.compute_initials(name)
            color = self._agent_list_handler.get_agent_color(name)
        else:
            parts = name.split()
            initials = (parts[0][0] + parts[1][0]).upper() if len(parts) >= 2 else name[:2].upper()
            color = "#6366f1"  # fallback indigo

        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row_box.set_halign(Gtk.Align.FILL)
        row_box.set_margin_start(4)
        row_box.set_margin_end(4)
        row_box.set_margin_top(4)
        row_box.set_margin_bottom(4)
        row_box.add_css_class("agent-row")

        # Avatar picture (44×44)
        avatar_picture = Gtk.Picture()
        avatar_picture.set_size_request(44, 44)
        avatar_picture.set_halign(Gtk.Align.CENTER)
        avatar_picture.set_valign(Gtk.Align.CENTER)
        avatar_picture.set_paintable(render_agent_icon(color, initials))

        # Name label
        name_lbl = Gtk.Label(label=name)
        name_lbl.set_halign(Gtk.Align.START)
        name_lbl.set_hexpand(True)
        name_lbl.set_margin_start(8)
        name_lbl.add_css_class("agent-name-label")

        # Buttons box: +/− toggle (if project active) + Chat
        buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        buttons_box.set_halign(Gtk.Align.END)

        # Toggle button: + (add) or − (remove) — only in project context
        toggle_btn = Gtk.Button()
        toggle_btn.set_size_request(28, 28)
        toggle_btn.add_css_class("flat")
        toggle_btn._agent_session_key = session_key
        toggle_btn._agent_name = name
        toggle_btn.connect("clicked", self._on_agent_toggle_clicked)
        if self._active_project_name:
            toggle_btn.set_label("−" if in_project else "+")
            toggle_btn.set_visible(True)
        else:
            toggle_btn.set_visible(False)

        # Chat button
        chat_btn = Gtk.Button(label="Chat")
        chat_btn.set_has_frame(False)
        chat_btn.add_css_class("agent-chat-btn")
        chat_btn._agent_session_key = session_key
        chat_btn._agent_name = name
        chat_btn.connect("clicked", self._on_agent_chat_clicked)

        avatar_picture.show()
        name_lbl.show()
        toggle_btn.show()
        chat_btn.show()

        buttons_box.append(toggle_btn)
        buttons_box.append(chat_btn)
        row_box.append(avatar_picture)
        row_box.append(name_lbl)
        row_box.append(buttons_box)
        row.set_child(row_box)
        row.show()
        return row

    def _on_agent_chat_clicked(self, button):
        """Handle Chat button click — delegate to handler, then open chat tab."""
        session_key = button._agent_session_key
        name = button._agent_name
        if self._agent_list_handler:
            self._agent_list_handler.on_chat_clicked(session_key, name)
        if self._on_agent_selected:
            self._on_agent_selected(session_key, name)

    def _on_agent_row_activated(self, list_box, row):
        """Called when an agent row is clicked — open/create chat tab."""
        if self._on_agent_selected is not None:
            self._on_agent_selected(row._session_key, row._agent_name)

    def _on_agent_toggle_clicked(self, button):
        """Add or remove an agent from the active project."""
        if not self._active_project_name:
            return
        session_key = button._agent_session_key
        members = load_members(self._active_project_name)
        if session_key in members:
            members.remove(session_key)
        else:
            members.append(session_key)
        save_members(self._active_project_name, members)
        self._refresh_agents_list()
        if self._on_project_members_changed:
            self._on_project_members_changed(self._active_project_name, members)

    # ── Prompts tab ─────────────────────────────────────────────────────────

    def _build_prompts_list(self):
        """Build a scrollable list of prompt files from the prompts/ directory."""
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)

        prompts = load_prompts()

        for display_name, content in prompts:
            row = Gtk.ListBoxRow()
            row._prompt_content = content

            label = Gtk.Label(label=display_name, xalign=0)
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            label.set_margin_start(8)
            label.set_margin_end(8)
            row.set_child(label)
            list_box.append(row)

        list_box.set_activate_on_single_click(False)
        list_box.connect("row_activated", self._on_prompt_row_activated)

        scroll.set_child(list_box)
        return scroll

    def _on_prompt_row_activated(self, list_box, row):
        """Called when a prompt row is double-clicked."""
        if self._on_prompt_selected is not None:
            self._on_prompt_selected(row._prompt_content)

