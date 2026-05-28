# ui/views/agent_builder.py
# GTK4 dialog for creating and editing user-defined agents.
#
# Pure view — receives data from AgentBuilderHandler, emits user actions
# back through callbacks (on_save, on_cancel).
#
# Architecture rule (ARCHITECTURE.md Section 9):
#   - Uses add_css_class() only, no inline CssProvider
#   - No business logic — delegates to handler for validation/persistence
#   - CSS classes: agent-builder-*

from __future__ import annotations

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib

from utils.mcp_config import load_mcp_servers, MCPConfigError


class AgentBuilderDialog:
    """GTK4 dialog for creating/editing agent definitions.

    If agent_def is provided, pre-fills the form for editing.
    If None, shows an empty form for creating a new agent.

    Args:
        parent: Parent Gtk.Window for transient setting.
        handler: AgentBuilderHandler — provides tool/prompt/provider options.
        agent_def: Optional existing agent dict to edit.
        on_save: Callback with the form dict when user clicks Save.
        on_cancel: Callback when user clicks Cancel or closes window.
    """

    def __init__(
        self,
        parent: Gtk.Window,
        *,
        handler,
        agent_def: dict | None = None,
        on_save=None,
        on_cancel=None,
    ):
        self._handler = handler
        self._on_save = on_save
        self._on_cancel = on_cancel
        self._is_edit = agent_def is not None
        self._original_si = {}  # preserved SI overrides from edit source
        self._tool_checks: dict[str, Gtk.CheckButton] = {}
        self._tool_count_label: Gtk.Label | None = None
        self._mcp_checks: dict[str, Gtk.CheckButton] = {}

        # ── Window setup ──────────────────────────────────────────────
        title = "Edit Agent" if self._is_edit else "Create Agent"
        self._window = Gtk.Window(title=title)
        self._window.set_transient_for(parent)
        self._window.set_modal(True)
        self._window.set_default_size(480, 620)
        self._window.add_css_class("agent-builder-window")

        self._window.connect("close-request", self._on_close_request)

        # ── Build form ────────────────────────────────────────────────
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar with title + buttons
        header = self._build_header(title)
        content.append(header)

        # Scrollable form body
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        form_box.set_margin_start(20)
        form_box.set_margin_end(20)
        form_box.set_margin_top(16)
        form_box.set_margin_bottom(16)

        # Form fields
        self._name_entry = self._add_field(form_box, "Name", Gtk.Entry(), "Agent name")
        self._emoji_entry = self._add_field(form_box, "Emoji", Gtk.Entry(), "🤖", max_width=80)
        self._role_entry = self._add_field(form_box, "Role", Gtk.Entry(), "e.g. coder, debugger, researcher")

        # Provider dropdown
        self._provider_dropdown = self._build_provider_dropdown()
        self._add_labeled(form_box, "Provider", self._provider_dropdown)

        # Model entry
        self._model_entry = self._add_field(form_box, "Model", Gtk.Entry(), "e.g. MiniMax-M2.7")

        # Prompts multi-select
        self._prompts_list = self._build_prompts_list()
        self._add_labeled(form_box, "System Prompts", self._prompts_list, expand=True)

        # Tool presets + checkboxes
        tools_section = self._build_tools_section()
        self._add_labeled(form_box, "Tools", tools_section, expand=True)

        # MCP server checkboxes
        mcp_section = self._build_mcp_section()
        self._add_labeled(form_box, "MCP Servers", mcp_section, expand=False)

        scroll.set_child(form_box)
        content.append(scroll)

        # Error label (hidden by default)
        self._error_label = Gtk.Label()
        self._error_label.add_css_class("agent-builder-error")
        self._error_label.set_visible(False)
        self._error_label.set_wrap(True)
        self._error_label.set_margin_start(20)
        self._error_label.set_margin_end(20)
        content.append(self._error_label)

        self._window.set_child(content)

        # Pre-fill if editing
        if agent_def:
            self._fill_form(agent_def)

    # ── Public API ────────────────────────────────────────────────────

    def get_values(self) -> dict:
        """Extract current form values into an agent_def dict."""
        name = self._name_entry.get_text().strip()
        emoji = self._emoji_entry.get_text().strip() or "🤖"
        role = self._role_entry.get_text().strip() or name.lower().replace(" ", "-")
        provider = self._get_selected_provider()
        model = self._model_entry.get_text().strip()

        prompts = self._get_selected_prompts()
        tools = self._get_selected_tools()

        return {
            "name": name,
            "emoji": emoji,
            "role": role,
            "prompts": prompts,
            "tools": tools,
            "provider": provider,
            "model": model,
            "mcp_servers": self._get_selected_mcp_servers(),
            "self_improvement": self._get_si_config(tools),
        }

    def show(self) -> None:
        """Present the dialog window."""
        self._window.present()
        # Focus name entry after window appears
        GLib.idle_add(lambda: self._name_entry.grab_focus() and False)

    def close(self) -> None:
        """Close the dialog window."""
        self._window.close()

    def show_errors(self, errors: list[str]) -> None:
        """Display validation errors."""
        self._error_label.set_text("\n".join(errors))
        self._error_label.set_visible(True)

    def _clear_errors(self) -> None:
        self._error_label.set_visible(False)

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self, title: str) -> Gtk.Box:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_start(16)
        header.set_margin_end(16)
        header.set_margin_top(12)
        header.set_margin_bottom(8)

        title_label = Gtk.Label(label=title)
        title_label.add_css_class("title-2")
        title_label.set_hexpand(True)
        title_label.set_xalign(0.0)
        header.append(title_label)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class("flat")
        cancel_btn.connect("clicked", lambda *_: self._do_cancel())
        header.append(cancel_btn)

        save_label = "Save" if self._is_edit else "Create"
        save_btn = Gtk.Button(label=save_label)
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda *_: self._do_save())
        header.append(save_btn)

        return header

    # ── Form helpers ──────────────────────────────────────────────────

    def _add_field(
        self,
        parent: Gtk.Box,
        label_text: str,
        entry: Gtk.Entry,
        placeholder: str = "",
        max_width: int = 0,
    ) -> Gtk.Entry:
        """Add a labeled entry field to the form."""
        entry.set_placeholder_text(placeholder)
        entry.set_hexpand(True)
        if max_width:
            entry.set_max_width_chars(6)
        self._add_labeled(parent, label_text, entry)
        return entry

    def _add_labeled(
        self,
        parent: Gtk.Box,
        label_text: str,
        widget: Gtk.Widget,
        expand: bool = False,
    ) -> None:
        """Add a labeled widget to the form."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label = Gtk.Label(label=label_text)
        label.add_css_class("caption")
        label.set_xalign(0.0)
        box.append(label)
        if expand:
            widget.set_vexpand(True)
        box.append(widget)
        parent.append(box)

    # ── Provider dropdown ─────────────────────────────────────────────

    def _build_provider_dropdown(self) -> Gtk.DropDown:
        providers = self._handler.get_provider_options()
        names = Gtk.StringList.new([p["name"] for p in providers] or ["(none)"])
        dropdown = Gtk.DropDown(model=names)
        dropdown.connect("notify::selected", self._on_provider_changed)
        return dropdown

    def _get_selected_provider(self) -> str:
        providers = self._handler.get_provider_options()
        idx = self._provider_dropdown.get_selected()
        if idx < len(providers):
            return providers[idx]["name"]
        return ""

    def _on_provider_changed(self, dropdown, _param) -> None:
        """When provider changes, pre-fill model from provider default."""
        providers = self._handler.get_provider_options()
        idx = dropdown.get_selected()
        if idx < len(providers) and providers[idx].get("default_model"):
            self._model_entry.set_text(providers[idx]["default_model"])

    # ── Prompts list ──────────────────────────────────────────────────

    def _build_prompts_list(self) -> Gtk.ScrolledWindow:
        prompts = self._handler.get_prompt_options()
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(100)
        scroll.set_max_content_height(160)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        list_box = Gtk.ListBox()
        list_box.add_css_class("agent-builder-prompt-list")
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)

        self._prompt_checks: dict[str, Gtk.CheckButton] = {}
        for p in prompts:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)

            check = Gtk.CheckButton(label=p["name"])
            check.add_css_class("agent-builder-prompt-check")
            self._prompt_checks[p["filepath"]] = check

            row.set_child(check)
            list_box.append(row)

        scroll.set_child(list_box)
        return scroll

    def _get_selected_prompts(self) -> list[str]:
        return [
            filepath for filepath, check in self._prompt_checks.items()
            if check.get_active()
        ]

    # ── Tools section with presets ────────────────────────────────────

    def _build_tools_section(self) -> Gtk.Box:
        """Build a categorized FlowBox grid of tool checkboxes.

        Tools are grouped into categories (Read, Write, Execute, Web). Unclassified
        tools fall into an "Other" category. Each tool displays as a simple checkbox
        with tooltip showing its description. Category headers are visually distinct.
        """
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Header row: presets on left, count badge on right
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        presets.add_css_class("agent-builder-presets")

        full_btn = Gtk.Button(label="Full Access")
        full_btn.add_css_class("flat")
        full_btn.connect("clicked", lambda *_: self._apply_preset("full"))

        readonly_btn = Gtk.Button(label="Read Only")
        readonly_btn.add_css_class("flat")
        readonly_btn.connect("clicked", lambda *_: self._apply_preset("readonly"))

        custom_btn = Gtk.Button(label="Custom")
        custom_btn.add_css_class("flat")
        custom_btn.connect("clicked", lambda *_: self._apply_preset("custom"))

        presets.append(full_btn)
        presets.append(readonly_btn)
        presets.append(custom_btn)
        header.append(presets)

        # Count badge (right side)
        self._tool_count_label = Gtk.Label(label="0/0 tools")
        self._tool_count_label.add_css_class("agent-builder-tool-count")
        self._tool_count_label.set_halign(Gtk.Align.END)
        self._tool_count_label.set_hexpand(True)
        header.append(self._tool_count_label)

        outer.append(header)

        # Category definitions
        CATEGORIES = [
            ("Read", {"read_file", "list_files", "search_files"}),
            ("Write", {"write_file", "edit_file"}),
            ("Execute", {"exec_command"}),
            ("Web", {"web_search", "web_fetch"}),
        ]

        tools = self._handler.get_tool_options()

        # Build a map from tool name → tool dict
        tool_map = {t["name"]: t for t in tools}

        # Track which tools we've placed
        placed = set()

        # Render each category
        for cat_name, cat_tools in CATEGORIES:
            # Get tools in this category that actually exist
            cat_matches = [(name, tool_map[name]) for name in sorted(cat_tools) if name in tool_map]
            if not cat_matches:
                continue

            placed.update(name for name, _ in cat_matches)

            # Category header
            cat_label = Gtk.Label(label=cat_name)
            cat_label.add_css_class("agent-builder-tool-cat-label")
            cat_label.set_halign(Gtk.Align.START)
            outer.append(cat_label)

            # FlowBox for this category
            flow = Gtk.FlowBox()
            flow.add_css_class("agent-builder-tool-grid")
            flow.set_min_children_per_line(2)
            flow.set_max_children_per_line(3)
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_homogeneous(True)
            outer.append(flow)

            # Checkboxes in this category
            for name, tool in cat_matches:
                check = Gtk.CheckButton(label=name)
                check.add_css_class("agent-builder-tool-check")
                # First line only — avoids "WHEN TO USE:" dev docs noise
                desc_first = tool["description"].split("\n")[0].strip()
                check.set_tooltip_text(desc_first)
                check.connect("toggled", lambda *_: self._update_tool_count())
                self._tool_checks[name] = check

                child = Gtk.FlowBoxChild()
                child.set_can_focus(False)
                child.set_child(check)
                flow.append(child)

        # "Other" category for any unclassified tools
        other_tools = [(name, tool_map[name]) for name in sorted(tool_map.keys()) if name not in placed]
        if other_tools:
            cat_label = Gtk.Label(label="Other")
            cat_label.add_css_class("agent-builder-tool-cat-label")
            cat_label.set_halign(Gtk.Align.START)
            outer.append(cat_label)

            flow = Gtk.FlowBox()
            flow.add_css_class("agent-builder-tool-grid")
            flow.set_min_children_per_line(2)
            flow.set_max_children_per_line(3)
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_homogeneous(True)
            outer.append(flow)

            for name, tool in other_tools:
                check = Gtk.CheckButton(label=name)
                check.add_css_class("agent-builder-tool-check")
                desc_first = tool["description"].split("\n")[0].strip()
                check.set_tooltip_text(desc_first)
                check.connect("toggled", lambda *_: self._update_tool_count())
                self._tool_checks[name] = check

                child = Gtk.FlowBoxChild()
                child.set_can_focus(False)
                child.set_child(check)
                flow.append(child)

        # Initialize count badge
        self._update_tool_count()

        return outer

    def _apply_preset(self, preset: str) -> None:
        """Apply a tool preset to all checkboxes."""
        read_only = {"read_file", "list_files", "search_files", "web_search", "web_fetch"}

        if preset == "full":
            for name, check in self._tool_checks.items():
                check.set_active(True)
        elif preset == "readonly":
            for name, check in self._tool_checks.items():
                check.set_active(name in read_only)
        # "custom" — leave as-is

        self._update_tool_count()

    def _update_tool_count(self) -> None:
        """Update the tool count badge label."""
        if self._tool_count_label is None:
            return
        total = len(self._tool_checks)
        selected = sum(1 for check in self._tool_checks.values() if check.get_active())
        self._tool_count_label.set_label(f"{selected}/{total} tools")

    def _get_selected_tools(self) -> list[str]:
        return [name for name, check in self._tool_checks.items() if check.get_active()]

    # ── MCP Servers section ────────────────────────────────────────────

    def _build_mcp_section(self) -> Gtk.Box:
        """Build MCP server checkbox list for the agent builder form."""
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        try:
            all_servers = load_mcp_servers()
        except (FileNotFoundError, OSError, MCPConfigError) as exc:
            dim = Gtk.Label(label="No MCP servers configured.\nAdd servers to ~/.config/crabcakes/mcp-servers.json")
            dim.add_css_class("dim-label")
            dim.set_justify(Gtk.Justification.LEFT)
            dim.set_xalign(0.0)
            dim.set_wrap(True)
            outer.append(dim)
            return outer

        # Only show enabled servers
        enabled_servers = {name: cfg for name, cfg in all_servers.items() if cfg.enabled}

        if not enabled_servers:
            dim = Gtk.Label(label="No MCP servers configured.\nAdd servers to ~/.config/crabcakes/mcp-servers.json")
            dim.add_css_class("dim-label")
            dim.set_justify(Gtk.Justification.LEFT)
            dim.set_xalign(0.0)
            dim.set_wrap(True)
            outer.append(dim)
            return outer

        list_box = Gtk.ListBox()
        list_box.add_css_class("agent-builder-mcp-list")
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)

        for name, cfg in enabled_servers.items():
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)

            check = Gtk.CheckButton(label=f"{name}  — {cfg.description[:60]}")
            check.add_css_class("agent-builder-mcp-check")
            self._mcp_checks[name] = check

            row.set_child(check)
            list_box.append(row)

        outer.append(list_box)
        return outer

    def _get_selected_mcp_servers(self) -> list[str]:
        """Return list of MCP server names whose checkboxes are active."""
        return [name for name, check in self._mcp_checks.items() if check.get_active()]

    # ── SI config ─────────────────────────────────────────────────────

    def _get_si_config(self, tools: list[str]) -> dict:
        """Build SI config based on selected tools + preserved overrides."""
        from utils.agent_defs import get_default_si_config
        can_write = "write_file" in tools or "edit_file" in tools
        defaults = get_default_si_config(can_write=can_write)
        # Merge preserved overrides on top of fresh defaults
        if self._original_si:
            return {**defaults, **self._original_si}
        return defaults

    # ── Pre-fill for editing ──────────────────────────────────────────

    def _fill_form(self, agent_def: dict) -> None:
        """Pre-fill form fields from an existing agent definition."""
        # Preserve original SI config for round-trip
        self._original_si = dict(agent_def.get("self_improvement", {}))

        self._name_entry.set_text(agent_def.get("name", ""))
        self._emoji_entry.set_text(agent_def.get("emoji", ""))
        self._role_entry.set_text(agent_def.get("role", ""))
        self._model_entry.set_text(agent_def.get("model", ""))

        # Select provider
        provider = agent_def.get("provider", "")
        providers = self._handler.get_provider_options()
        for i, p in enumerate(providers):
            if p["name"] == provider:
                self._provider_dropdown.set_selected(i)
                break

        # Check prompts
        selected_prompts = set(agent_def.get("prompts", []))
        for filepath, check in self._prompt_checks.items():
            check.set_active(filepath in selected_prompts)

        # Check tools
        selected_tools = set(agent_def.get("tools", []))
        for name, check in self._tool_checks.items():
            check.set_active(name in selected_tools)

        self._update_tool_count()

        # Check MCP servers
        selected_mcp = set(agent_def.get("mcp_servers", []))
        for name, check in self._mcp_checks.items():
            check.set_active(name in selected_mcp)

    # ── Actions ───────────────────────────────────────────────────────

    def _do_save(self) -> None:
        """User clicked Save/Create."""
        self._clear_errors()
        values = self.get_values()
        if self._on_save:
            self._on_save(values)

    def _do_cancel(self) -> None:
        """User clicked Cancel."""
        if self._on_cancel:
            self._on_cancel()
        self._window.destroy()

    def _on_close_request(self) -> bool:
        """Window close button clicked."""
        if self._on_cancel:
            self._on_cancel()
        return False  # allow close
