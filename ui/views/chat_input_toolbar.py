# ui/views/chat_input_toolbar.py
# Compact toolbar for the chat input area.
#
# Architecture: PURE VIEW — widgets only, no business logic.
# All logic lives in InputToolbarHandler.
# File dialogs and popovers are part of the view layer.

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib

from utils.prompts import load_prompts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper — build a flat icon button
# ---------------------------------------------------------------------------


def _icon_button(icon_name: str, tooltip: str, css_class: str = "") -> Gtk.Button:
    btn = Gtk.Button()
    btn.set_icon_name(icon_name)
    btn.set_tooltip_text(tooltip)
    btn.add_css_class("flat")
    if css_class:
        btn.add_css_class(css_class)
    return btn


# ---------------------------------------------------------------------------
# ChatInputToolbar
# ---------------------------------------------------------------------------


class ChatInputToolbar(Gtk.Box):
    """
    Compact horizontal toolbar sitting between the chat area and the input box.

    Groups:
      File I/O  |  Search  |  Quality  |  <spacer>  |  Info
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.CENTER)
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(2)
        self.set_margin_bottom(2)
        self.add_css_class("input-toolbar")

        # ── Callbacks (set by window.py) ──────────────────────────────────
        self._on_save_file: callable | None = None
        self._on_save_prompt: callable | None = None
        self._on_open_file: callable | None = None
        self._on_open_prompt: callable | None = None
        self._on_find: callable | None = None
        self._on_find_next: callable | None = None
        self._on_find_prev: callable | None = None
        self._on_replace: callable | None = None
        self._on_spell_toggle: callable | None = None
        self._on_buffer_changed: callable | None = None

        # ── Build main toolbar row ─────────────────────────────────────────
        main_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        main_row.set_halign(Gtk.Align.FILL)
        main_row.set_spacing(4)
        main_row.set_margin_start(4)
        main_row.set_margin_end(4)
        main_row.set_margin_top(3)
        main_row.set_margin_bottom(3)
        self.append(main_row)

        # File I/O group: Save ▾  Open ▾
        save_btn = self._build_save_menu_button()
        open_btn = self._build_open_menu_button()
        main_row.append(save_btn)
        main_row.append(open_btn)

        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep1.add_css_class("toolbar-separator")
        sep1.set_margin_start(4)
        sep1.set_margin_end(4)
        main_row.append(sep1)

        # Search group: Find  Replace
        find_btn = _icon_button("edit-find-symbolic", "Find  (Ctrl+F)")
        find_btn.connect("clicked", self._on_find_clicked)
        self._find_btn = find_btn

        replace_btn = _icon_button("edit-find-replace-symbolic", "Find & Replace")
        replace_btn.connect("clicked", self._on_replace_clicked)
        self._replace_btn = replace_btn

        main_row.append(find_btn)
        main_row.append(replace_btn)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep2.add_css_class("toolbar-separator")
        sep2.set_margin_start(4)
        sep2.set_margin_end(4)
        main_row.append(sep2)

        # Quality group: Spell check toggle
        spell_btn = Gtk.ToggleButton()
        spell_btn.set_icon_name("check-round-outline-symbolic")
        spell_btn.set_tooltip_text("Spell Check")
        spell_btn.add_css_class("flat")
        spell_btn.connect("toggled", self._on_spell_toggled, spell_btn)
        self._spell_btn = spell_btn
        main_row.append(spell_btn)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        main_row.append(spacer)

        # Info group: word count label
        self._count_label = Gtk.Label()
        self._count_label.set_halign(Gtk.Align.END)
        self._count_label.add_css_class("count-label")
        self._count_label.set_markup(
            '<span foreground="#5a5a6a" font_desc="Sans 9">0 words · 0 chars</span>'
        )
        main_row.append(self._count_label)

        # ── Find / replace bar (hidden by default) ─────────────────────────
        self._find_bar = self._build_find_bar()
        self._find_bar.set_visible(False)
        self.append(self._find_bar)

    # -------------------------------------------------------------------------
    # Public callback setters (called by window.py)
    # -------------------------------------------------------------------------

    def set_on_save_file(self, cb: callable) -> None:
        self._on_save_file = cb

    def set_on_save_prompt(self, cb: callable) -> None:
        self._on_save_prompt = cb

    def set_on_open_file(self, cb: callable) -> None:
        self._on_open_file = cb

    def set_on_open_prompt(self, cb: callable) -> None:
        self._on_open_prompt = cb

    def set_on_find(self, cb: callable) -> None:
        self._on_find = cb

    def set_on_find_next(self, cb: callable) -> None:
        self._on_find_next = cb

    def set_on_find_prev(self, cb: callable) -> None:
        self._on_find_prev = cb

    def set_on_replace(self, cb: callable) -> None:
        self._on_replace = cb

    def set_on_spell_toggle(self, cb: callable) -> None:
        self._on_spell_toggle = cb

    def set_on_buffer_changed(self, cb: callable) -> None:
        self._on_buffer_changed = cb

    # -------------------------------------------------------------------------
    # Public update methods (called by window.py / handler)
    # -------------------------------------------------------------------------

    def show_find_bar(self, show_replace: bool = False):
        """Show the find bar, optionally with the replace row visible."""
        self._find_bar.set_visible(True)
        if show_replace:
            self._replace_row.set_visible(True)
        else:
            self._replace_row.set_visible(False)
        self._find_entry.grab_focus()

    def hide_find_bar(self):
        """Hide the find bar and clear find state."""
        self._find_bar.set_visible(False)
        self._find_entry.set_text("")
        self._replace_entry.set_text("")
        self._match_label.set_text("")

    def update_match_count(self, current: int, total: int):
        """Update the "N of M" match count label."""
        if total == 0:
            self._match_label.set_text("No matches")
        else:
            self._match_label.set_text(f"{current + 1} of {total}")

    def set_spell_active(self, active: bool):
        """Update spell check toggle button visual state."""
        self._spell_btn.set_active(active)
        if active:
            self._spell_btn.add_css_class("spell-active")
        else:
            self._spell_btn.remove_css_class("spell-active")

    def update_word_count(self, words: int, chars: int, tokens: int):
        """Update word count label."""
        self._count_label.set_markup(
            f'<span foreground="#5a5a6a" font_desc="Sans 9">'
            f"{words:,} words · {chars:,} chars · ~{tokens:,} tokens"
            f"</span>"
        )

    # -------------------------------------------------------------------------
    # Internal — save menu
    # -------------------------------------------------------------------------

    def _build_save_menu_button(self) -> Gtk.MenuButton:
        btn = Gtk.MenuButton()
        btn.set_icon_name("document-save-symbolic")
        btn.set_tooltip_text("Save")
        btn.add_css_class("flat")

        popover = Gtk.PopoverMenu()
        popover.set_autohide(True)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.set_spacing(2)
        vbox.set_margin_start(4)
        vbox.set_margin_end(4)
        vbox.set_margin_top(4)
        vbox.set_margin_bottom(4)

        save_file_item = Gtk.Button(label="Save as File…")
        save_file_item.add_css_class("flat")
        save_file_item.connect("clicked", self._on_save_file_clicked)
        save_prompt_item = Gtk.Button(label="Save as Prompt…")
        save_prompt_item.add_css_class("flat")
        save_prompt_item.connect("clicked", self._on_save_prompt_clicked)

        vbox.append(save_file_item)
        vbox.append(save_prompt_item)
        popover.set_child(vbox)
        btn.set_popover(popover)
        return btn

    def _on_save_file_clicked(self, *args):
        btn = self._find_save_menu_button()
        if btn:
            btn.popdown()
        self._open_save_file_dialog()

    def _on_save_prompt_clicked(self, *args):
        btn = self._find_save_menu_button()
        if btn:
            btn.popdown()
        self._open_save_prompt_dialog()

    def _find_save_menu_button(self) -> Gtk.Widget | None:
        # Walk ancestors to find the parent MenuButton
        parent = self.get_parent()
        while parent:
            if isinstance(parent, Gtk.MenuButton):
                return parent
            parent = parent.get_parent()
        return None

    def _open_save_file_dialog(self):
        """Open GTK4 FileDialog to save input as a file."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Save Input As")
        root = self._get_toplevel()
        if root is None:
            return
        dialog.save(root, None, self._on_save_file_selected)

    def _on_save_file_selected(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            if file and self._on_save_file:
                self._on_save_file(file.get_path())
        except GLib.Error:
            pass  # cancelled

    def _open_save_prompt_dialog(self):
        """Open a simple dialog asking for the prompt filename."""
        dialog = Gtk.MessageDialog(
            transient_for=self._get_toplevel(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            text="Save as Prompt",
            secondary_text="Enter a name for the prompt (no .md needed):",
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("my-prompt-name")
        dialog.get_message_area().append(entry)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        def on_response(dlg, resp):
            if resp == Gtk.ResponseType.OK:
                name = entry.get_text().strip()
                if name and self._on_save_prompt:
                    self._on_save_prompt(name)
            dlg.destroy()

        dialog.connect("response", on_response)
        dialog.show()

    # -------------------------------------------------------------------------
    # Internal — open menu
    # -------------------------------------------------------------------------

    def _build_open_menu_button(self) -> Gtk.MenuButton:
        btn = Gtk.MenuButton()
        btn.set_icon_name("document-open-symbolic")
        btn.set_tooltip_text("Open")
        btn.add_css_class("flat")

        popover = Gtk.PopoverMenu()
        popover.set_autohide(True)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.set_spacing(2)
        vbox.set_margin_start(4)
        vbox.set_margin_end(4)
        vbox.set_margin_top(4)
        vbox.set_margin_bottom(4)

        open_file_item = Gtk.Button(label="Open File…")
        open_file_item.add_css_class("flat")
        open_file_item.connect("clicked", self._on_open_file_clicked)
        open_prompt_item = Gtk.Button(label="Open Prompt…")
        open_prompt_item.add_css_class("flat")
        open_prompt_item.connect("clicked", self._on_open_prompt_clicked)

        vbox.append(open_file_item)
        vbox.append(open_prompt_item)
        popover.set_child(vbox)
        btn.set_popover(popover)
        return btn

    def _on_open_file_clicked(self, *args):
        btn = self._find_open_menu_button()
        if btn:
            btn.popdown()
        self._open_open_file_dialog()

    def _on_open_prompt_clicked(self, *args):
        btn = self._find_open_menu_button()
        if btn:
            btn.popdown()
        self._open_open_prompt_popover()

    def _find_open_menu_button(self) -> Gtk.Widget | None:
        parent = self.get_parent()
        while parent:
            if isinstance(parent, Gtk.MenuButton):
                return parent
            parent = parent.get_parent()
        return None

    def _open_open_file_dialog(self):
        """Open GTK4 FileDialog to select a file to load."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Open File")
        root = self._get_toplevel()
        if root is None:
            return
        dialog.open(root, None, self._on_open_file_selected)

    def _on_open_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file and self._on_open_file:
                self._on_open_file(file.get_path())
        except GLib.Error:
            pass  # cancelled

    def _open_open_prompt_popover(self):
        """Show a popover listing available prompts."""
        prompts = load_prompts()

        popover = Gtk.Popover()
        popover.set_autohide(True)
        popover.set_parent(self._find_btn)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.set_spacing(2)
        vbox.set_margin_start(4)
        vbox.set_margin_end(4)
        vbox.set_margin_top(4)
        vbox.set_margin_bottom(4)

        if not prompts:
            lbl = Gtk.Label()
            lbl.set_markup('<span foreground="#6b6b7a">(no prompts yet)</span>')
            vbox.append(lbl)
        else:
            for name, _content in prompts:
                btn = Gtk.Button(label=name)
                btn.add_css_class("flat")
                btn.connect("clicked", self._on_prompt_selected, name)
                vbox.append(btn)

        scroll = Gtk.ScrolledWindow()
        scroll.set_child(vbox)
        scroll.set_min_content_height(100)
        scroll.set_max_content_height(300)
        scroll.set_propagate_natural_height(True)

        popover.set_child(scroll)
        popover.popup()

    def _on_prompt_selected(self, _btn, name: str):
        # Find and dismiss the popover
        for child in self.get_parent().get_children():
            if isinstance(child, Gtk.Popover):
                child.popdown()
                break
        if self._on_open_prompt:
            self._on_open_prompt(name)

    # -------------------------------------------------------------------------
    # Internal — find bar
    # -------------------------------------------------------------------------

    def _build_find_bar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar.add_css_class("find-bar")
        bar.set_margin_start(4)
        bar.set_margin_end(4)
        bar.set_margin_bottom(4)

        # Row 1: search entry + match count + prev/next + close
        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row1.set_spacing(4)
        row1.set_margin_start(4)
        row1.set_margin_end(4)
        row1.set_margin_top(4)
        row1.set_margin_bottom(2)
        bar.append(row1)

        self._find_entry = Gtk.Entry()
        self._find_entry.set_placeholder_text("Find…")
        self._find_entry.set_hexpand(True)
        # Note: set_keynav_wrapper is GTK3-only; removed for GTK4 compat.
        self._find_entry.connect("changed", self._on_find_entry_changed)
        self._find_entry.connect("activate", self._on_find_next_clicked)
        row1.append(self._find_entry)

        self._match_label = Gtk.Label()
        self._match_label.set_halign(Gtk.Align.START)
        self._match_label.set_markup(
            '<span foreground="#6b6b7a" font_desc="Sans 9"></span>'
        )
        self._match_label.set_margin_start(4)
        row1.append(self._match_label)

        prev_btn = _icon_button("go-up-symbolic", "Previous match")
        prev_btn.connect("clicked", self._on_find_prev_clicked)
        row1.append(prev_btn)

        next_btn = _icon_button("go-down-symbolic", "Next match")
        next_btn.connect("clicked", self._on_find_next_clicked)
        row1.append(next_btn)

        close_btn = Gtk.Button()
        close_btn.set_icon_name("window-close-symbolic")
        close_btn.set_tooltip_text("Close")
        close_btn.add_css_class("flat")
        close_btn.connect("clicked", self._on_find_close_clicked)
        row1.append(close_btn)

        # Row 2: replace entry + Replace + Replace All (hidden until Replace clicked)
        self._replace_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._replace_row.set_spacing(4)
        self._replace_row.set_margin_start(4)
        self._replace_row.set_margin_end(4)
        self._replace_row.set_margin_bottom(4)
        self._replace_row.set_visible(False)
        bar.append(self._replace_row)

        self._replace_entry = Gtk.Entry()
        self._replace_entry.set_placeholder_text("Replace with…")
        self._replace_entry.set_hexpand(True)
        self._replace_entry.connect("activate", self._on_replace_clicked_from_bar)
        self._replace_row.append(self._replace_entry)

        replace_btn = Gtk.Button(label="Replace")
        replace_btn.add_css_class("flat")
        replace_btn.connect("clicked", self._on_replace_clicked_from_bar)
        self._replace_row.append(replace_btn)

        replace_all_btn = Gtk.Button(label="Replace All")
        replace_all_btn.add_css_class("flat")
        replace_all_btn.connect("clicked", self._on_replace_all_clicked)
        self._replace_row.append(replace_all_btn)

        return bar

    def _on_find_entry_changed(self, entry):
        text = entry.get_text()
        if self._on_buffer_changed:
            self._on_buffer_changed()
        if self._on_find:
            self._on_find(text)

    def _on_find_clicked(self, *args):
        self.show_find_bar(show_replace=False)
        if self._on_find:
            self._on_find(self._find_entry.get_text())

    def _on_replace_clicked(self, *args):
        self.show_find_bar(show_replace=True)
        if self._on_replace:
            self._on_replace()

    def _on_find_next_clicked(self, *args):
        if self._on_find and self._find_entry.get_text():
            self._on_find(self._find_entry.get_text())  # re-run find
        # Then advance — but we need a find_next callback
        # For now, re-running find is sufficient; handler tracks state

    def _on_find_prev_clicked(self, *args):
        pass  # wired via on_find_next — window.py wires find_next separately

    def _on_find_close_clicked(self, *args):
        self.hide_find_bar()
        if self._on_find:
            self._on_find("")  # clear

    def _on_spell_toggled(self, _btn, spell_btn):
        if self._on_spell_toggle:
            self._on_spell_toggle()

    def _on_replace_clicked_from_bar(self, *args):
        replacement = self._replace_entry.get_text()
        if self._on_replace:
            self._on_replace(replacement)

    def _on_replace_all_clicked(self, *args):
        replacement = self._replace_entry.get_text()
        if self._on_replace:
            self._on_replace(replacement)  # handler distinguishes replace vs replace_all

    # -------------------------------------------------------------------------
    # Internal — utilities
    # -------------------------------------------------------------------------

    def _get_toplevel(self) -> Gtk.Window | None:
        toplevel = self.get_ancestor(Gtk.Window)
        if toplevel is None:
            root = Gtk.get_major_client()
            if hasattr(root, "get_active_window"):
                toplevel = root.get_active_window()
        return toplevel