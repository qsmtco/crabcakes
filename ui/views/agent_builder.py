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
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Preset buttons row
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
        outer.append(presets)

        # Tool checkboxes in a scrollable list
        tools = self._handler.get_tool_options()
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(80)
        scroll.set_max_content_height(160)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        tool_box = Gtk.ListBox()
        tool_box.add_css_class("agent-builder-tool-list")
        tool_box.set_selection_mode(Gtk.SelectionMode.NONE)

        for t in tools:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)

            check = Gtk.CheckButton(label=f"{t['name']} — {t['description'][:60]}")
            check.add_css_class("agent-builder-tool-check")
            self._tool_checks[t["name"]] = check

            row.set_child(check)
            tool_box.append(row)

        scroll.set_child(tool_box)
        outer.append(scroll)

        return outer

    def _apply_preset(self, preset: str) -> None:
        """Apply a tool preset to all checkboxes."""
        all_tools = list(self._tool_checks.keys())
        read_only = {"read_file", "list_files", "search_files", "web_search", "web_fetch"}

        if preset == "full":
            for name, check in self._tool_checks.items():
                check.set_active(True)
        elif preset == "readonly":
            for name, check in self._tool_checks.items():
                check.set_active(name in read_only)
        # "custom" — leave as-is

    def _get_selected_tools(self) -> list[str]:
        return [name for name, check in self._tool_checks.items() if check.get_active()]

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
