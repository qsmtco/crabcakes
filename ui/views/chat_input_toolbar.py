"""ChatInputToolbar — compact toolbar for the chat input area.

Pure view — creates GTK widgets, emits callbacks. No business logic.
All logic lives in InputToolbarHandler.

Widget structure:
  ChatInputToolbar (Gtk.Box, VERTICAL)
  ├── bar (Gtk.Box, HORIZONTAL) — the main toolbar
  │   ├── save_btn (Gtk.MenuButton → save popover)
  │   ├── open_btn (Gtk.MenuButton → open popover)
  │   ├── sep_1 (Gtk.Separator)
  │   ├── find_btn (Gtk.Button, 🔍)
  │   ├── replace_btn (Gtk.Button, 🔀)
  │   ├── sep_2 (Gtk.Separator)
  │   ├── spell_btn (Gtk.ToggleButton, ✓ ABC)
  │   ├── spacer (Gtk.Box, hexpand=True)
  │   └── count_label (Gtk.Label)
  └── find_bar (Gtk.Box, VERTICAL, hidden by default)
      ├── search_row (Gtk.Box): [search_entry, match_label, prev/next/close]
      └── replace_row (Gtk.Box, hidden): [replace_entry, Replace, Replace All]
"""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")

from gi.repository import Gdk, Gio, GLib, Gtk
from utils.prompts import load_prompts


class ChatInputToolbar(Gtk.Box):
    """Compact toolbar for the chat input area.

    Provides file I/O, find/replace, spell check, word count.
    Pure view — all logic lives in InputToolbarHandler.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.START)
        self.add_css_class("input-toolbar")

        # Primary callbacks — set by window.py
        self._on_save_file: callable | None = None
        self._on_save_prompt: callable | None = None
        self._on_open_file: callable | None = None
        self._on_open_prompt: callable | None = None
        self._on_find: callable | None = None
        self._on_replace: callable | None = None
        self._on_spell_toggle: callable | None = None
        self._on_buffer_changed: callable | None = None
        self._on_suggestion_apply: callable | None = None

        # Navigation callbacks (set separately from find/replace)
        self._on_find_prev: callable | None = None
        self._on_find_next: callable | None = None

        self._find_bar_visible = False

        self._build_toolbar()
        self._build_find_bar()

    # ── Widget construction ───────────────────────────────────────────────

    def _build_toolbar(self):
        """Build the top toolbar row."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bar.set_halign(Gtk.Align.FILL)
        bar.set_valign(Gtk.Align.CENTER)
        bar.set_margin_start(8)
        bar.set_margin_end(8)
        bar.set_margin_top(4)
        bar.set_margin_bottom(4)

        # Save ▾
        save_popover = self._build_save_popover()
        save_btn = Gtk.MenuButton(label="Save ▾")
        save_btn.set_popover(save_popover)
        save_btn.add_css_class("flat")
        bar.append(save_btn)

        # Open ▾
        open_popover = self._build_open_popover()
        open_btn = Gtk.MenuButton(label="Open ▾")
        open_btn.set_popover(open_popover)
        open_btn.add_css_class("flat")
        bar.append(open_btn)

        # Separator
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep1.add_css_class("toolbar-separator")
        bar.append(sep1)

        # Find button
        find_btn = Gtk.Button(label="🔍")
        find_btn.set_tooltip_text("Find (Ctrl+F)")
        find_btn.connect("clicked", self._on_find_clicked)
        find_btn.add_css_class("flat")
        bar.append(find_btn)

        # Replace button
        replace_btn = Gtk.Button(label="🔀")
        replace_btn.set_tooltip_text("Replace")
        replace_btn.connect("clicked", self._on_replace_clicked)
        replace_btn.add_css_class("flat")
        bar.append(replace_btn)

        # Separator
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep2.add_css_class("toolbar-separator")
        bar.append(sep2)

        # Spell check toggle
        self._spell_btn = Gtk.ToggleButton(label="✓ ABC")
        self._spell_btn.set_tooltip_text("Toggle spell check")
        self._spell_btn.connect("toggled", self._on_spell_toggled)
        self._spell_btn.add_css_class("flat")
        bar.append(self._spell_btn)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        # Word count label
        self._count_label = Gtk.Label(label="0 words · 0 chars")
        self._count_label.add_css_class("count-label")
        self._count_label.set_halign(Gtk.Align.END)
        bar.append(self._count_label)

        self.append(bar)

    def _build_save_popover(self) -> Gtk.Popover:
        """Build Save ▾ popover menu."""
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        save_file_btn = Gtk.Button(label="Save as File...")
        save_file_btn.add_css_class("flat")
        save_file_btn.connect("clicked", self._on_save_file_clicked)
        box.append(save_file_btn)

        save_prompt_btn = Gtk.Button(label="Save as Prompt...")
        save_prompt_btn.add_css_class("flat")
        save_prompt_btn.connect("clicked", self._on_save_prompt_clicked)
        box.append(save_prompt_btn)

        popover.set_child(box)
        return popover

    def _build_open_popover(self) -> Gtk.Popover:
        """Build Open ▾ popover menu."""
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        open_file_btn = Gtk.Button(label="Open File...")
        open_file_btn.add_css_class("flat")
        open_file_btn.connect("clicked", self._on_open_file_clicked)
        box.append(open_file_btn)

        open_prompt_btn = Gtk.Button(label="Open Prompt...")
        open_prompt_btn.add_css_class("flat")
        open_prompt_btn.connect("clicked", self._on_open_prompt_clicked)
        box.append(open_prompt_btn)

        popover.set_child(box)
        return popover

    def _build_find_bar(self):
        """Build the find/replace bar (hidden by default)."""
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        bar.set_halign(Gtk.Align.FILL)
        bar.set_valign(Gtk.Align.START)
        bar.add_css_class("find-bar")
        bar.set_margin_start(8)
        bar.set_margin_end(8)
        bar.set_margin_bottom(4)
        bar.set_visible(False)
        self._find_bar = bar

        # Search row
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        search_row.set_halign(Gtk.Align.FILL)

        self._search_entry = Gtk.Entry()
        self._search_entry.set_placeholder_text("Find...")
        self._search_entry.set_hexpand(True)
        self._search_entry.connect("changed", self._on_search_changed)
        self._search_entry.connect("activate", self._on_search_activate)
        search_row.append(self._search_entry)

        self._match_label = Gtk.Label(label="")
        self._match_label.add_css_class("count-label")
        self._match_label.set_margin_start(6)
        self._match_label.set_margin_end(6)
        search_row.append(self._match_label)

        prev_btn = Gtk.Button(label="▲")
        prev_btn.add_css_class("flat")
        prev_btn.set_tooltip_text("Previous match")
        prev_btn.connect("clicked", self._on_find_prev_clicked)
        search_row.append(prev_btn)

        next_btn = Gtk.Button(label="▼")
        next_btn.add_css_class("flat")
        next_btn.set_tooltip_text("Next match")
        next_btn.connect("clicked", self._on_find_next_clicked)
        search_row.append(next_btn)

        close_btn = Gtk.Button(label="✕")
        close_btn.add_css_class("flat")
        close_btn.set_tooltip_text("Close find bar")
        close_btn.connect("clicked", self._on_find_close)
        search_row.append(close_btn)

        bar.append(search_row)

        # Replace row (hidden by default)
        replace_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        replace_row.set_halign(Gtk.Align.FILL)
        replace_row.set_visible(False)
        self._replace_row = replace_row

        self._replace_entry = Gtk.Entry()
        self._replace_entry.set_placeholder_text("Replace with...")
        self._replace_entry.set_hexpand(True)
        self._replace_entry.connect("activate", self._on_replace_activate)
        replace_row.append(self._replace_entry)

        replace_btn = Gtk.Button(label="Replace")
        replace_btn.connect("clicked", self._on_replace_current)
        replace_row.append(replace_btn)

        replace_all_btn = Gtk.Button(label="Replace All")
        replace_all_btn.connect("clicked", self._on_replace_all)
        replace_row.append(replace_all_btn)

        bar.append(replace_row)

        self.append(bar)

    # ── Callbacks ─────────────────────────────────────────────────────────

    def set_on_save_file(self, cb: callable) -> None:
        self._on_save_file = cb

    def set_on_save_prompt(self, cb: callable) -> None:
        self._on_save_prompt = cb

    def set_on_open_file(self, cb: callable) -> None:
        self._on_open_file = cb

    def set_on_open_prompt(self, cb: callable) -> None:
        self._on_open_prompt = cb

    def set_on_find(self, cb: callable) -> None:
        """Set callback for find text changes (search_text str → None)."""
        self._on_find = cb

    def set_on_replace(self, cb: callable) -> None:
        """Set callback for replace action (replacement str, current_only bool → None)."""
        self._on_replace = cb

    def set_on_spell_toggle(self, cb: callable) -> None:
        self._on_spell_toggle = cb

    def set_on_buffer_changed(self, cb: callable) -> None:
        self._on_buffer_changed = cb

    def set_on_suggestion_apply(self, cb: callable) -> None:
        self._on_suggestion_apply = cb

    def set_on_find_prev(self, cb: callable) -> None:
        """Set callback for find-prev navigation (→ (current, total))."""
        self._on_find_prev = cb

    def set_on_find_next(self, cb: callable) -> None:
        """Set callback for find-next navigation (→ (current, total))."""
        self._on_find_next = cb

    # ── File dialog handlers ──────────────────────────────────────────────

    def _on_save_file_clicked(self, btn: Gtk.Button):
        self._close_all_popovers()
        dialog = Gtk.FileDialog()
        dialog.set_title("Save Input As")
        root = self.get_root()
        if root is None:
            return
        dialog.save(root, None, self._on_save_file_selected)

    def _on_save_file_selected(self, dialog: Gtk.FileDialog, result: Gio.Task):
        try:
            file = dialog.save_finish(result)
            if file and self._on_save_file:
                self._on_save_file(file.get_path())
        except GLib.Error:
            pass

    def _on_save_prompt_clicked(self, btn: Gtk.Button):
        self._close_all_popovers()
        root = self.get_root()
        if root is None:
            return

        dialog = Gtk.Dialog(
            title="Save Prompt",
            transient_for=root,
            modal=True,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)

        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        lbl = Gtk.Label(label="Prompt name (no .md needed):")
        content.append(lbl)

        entry = Gtk.Entry()
        entry.set_placeholder_text("my-prompt-name")
        entry.set_hexpand(True)
        content.append(entry)

        def on_response(dlg, response_id):
            if response_id == Gtk.ResponseType.ACCEPT:
                name = entry.get_text().strip()
                if name and self._on_save_prompt:
                    self._on_save_prompt(name)
            dlg.destroy()

        dialog.connect("response", on_response)
        dialog.show()

    def _on_open_file_clicked(self, btn: Gtk.Button):
        self._close_all_popovers()
        dialog = Gtk.FileDialog()
        dialog.set_title("Open File")
        root = self.get_root()
        if root is None:
            return
        dialog.open(root, None, self._on_open_file_selected)

    def _on_open_file_selected(self, dialog: Gtk.FileDialog, result: Gio.Task):
        try:
            file = dialog.open_finish(result)
            if file and self._on_open_file:
                self._on_open_file(file.get_path())
        except GLib.Error:
            pass

    def _on_open_prompt_clicked(self, btn: Gtk.Button):
        self._close_all_popovers()
        popover = Gtk.Popover()
        popover.set_parent(btn)
        popover.set_position(Gtk.PositionType.BOTTOM)

        prompts = load_prompts()

        list_box = Gtk.ListBox()
        list_box.add_css_class("data-list")

        if not prompts:
            empty_lbl = Gtk.Label(label="No prompts yet")
            empty_lbl.set_margin_top(8)
            empty_lbl.set_margin_bottom(8)
            list_box.append(empty_lbl)
        else:
            for name, _content in prompts:
                row = Gtk.ListBoxRow()
                lbl = Gtk.Label(label=name, halign=Gtk.Align.START)
                lbl.set_margin_top(6)
                lbl.set_margin_bottom(6)
                lbl.set_margin_start(12)
                lbl.set_margin_end(12)
                row.set_child(lbl)
                row.connect("activated", self._on_prompt_row_activated, name)
                list_box.append(row)

        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(150)
        scroll.set_max_content_height(350)
        scroll.set_child(list_box)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(scroll)

        popover.set_child(outer)
        popover.popup()

    def _on_prompt_row_activated(self, row: Gtk.ListBoxRow, name: str):
        popover = row.get_parent().get_parent()
        popover.popdown()
        if self._on_open_prompt:
            self._on_open_prompt(name)

    # ── Find/Replace bar ───────────────────────────────────────────────────

    def _on_find_clicked(self, btn: Gtk.Button):
        self.show_find_bar(show_replace=False)

    def _on_replace_clicked(self, btn: Gtk.Button):
        self.show_find_bar(show_replace=True)

    def show_find_bar(self, show_replace: bool = False):
        """Show the find bar (optionally with replace row)."""
        self._find_bar.set_visible(True)
        self._replace_row.set_visible(show_replace)
        self._find_bar_visible = True
        self._search_entry.grab_focus()

    def hide_find_bar(self):
        """Hide the find bar and clear find state."""
        self._find_bar.set_visible(False)
        self._find_bar_visible = False
        self._search_entry.set_text("")
        self._replace_entry.set_text("")
        self._match_label.set_text("")

    def _on_search_changed(self, entry: Gtk.Entry):
        if self._on_find:
            self._on_find(entry.get_text())

    def _on_search_activate(self, entry: Gtk.Entry):
        """Enter in search field → advance to next match."""
        if self._on_find_next:
            current, total = self._on_find_next()
            self.update_match_count(current, total)

    def _on_find_prev_clicked(self, btn: Gtk.Button):
        if self._on_find_prev:
            current, total = self._on_find_prev()
            self.update_match_count(current, total)

    def _on_find_next_clicked(self, btn: Gtk.Button):
        if self._on_find_next:
            current, total = self._on_find_next()
            self.update_match_count(current, total)

    def _on_find_close(self, btn: Gtk.Button):
        self.hide_find_bar()
        if self._on_find:
            self._on_find("")  # clear find state in handler

    def _on_replace_activate(self, entry: Gtk.Entry):
        self._on_replace_current(entry)

    def _on_replace_current(self, btn: Gtk.Button):
        if self._on_replace:
            self._on_replace(self._replace_entry.get_text(), current_only=True)

    def _on_replace_all(self, btn: Gtk.Button):
        if self._on_replace:
            self._on_replace(self._replace_entry.get_text(), current_only=False)

    # ── Spell check ───────────────────────────────────────────────────────

    def _on_spell_toggled(self, btn: Gtk.ToggleButton):
        if self._on_spell_toggle:
            self._on_spell_toggle()

    # ── View update methods (called by window/handler) ───────────────────

    def update_match_count(self, current: int, total: int):
        """Update match count label: '3 of 12' or 'No matches'."""
        if total == 0:
            self._match_label.set_text("No matches")
        elif current < 0:
            self._match_label.set_text(f"{total} match{'es' if total != 1 else ''}")
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
        """Update word count label: '142 words · 1,847 chars · ~370 tokens'."""
        self._count_label.set_text(f"{words} words · {chars:,} chars · ~{tokens} tokens")

    def apply_spell_suggestion(self, word: str, suggestion: str):
        """Replace a misspelled word with the selected suggestion."""
        if self._on_suggestion_apply:
            self._on_suggestion_apply(word, suggestion)

    # ── Utility ──────────────────────────────────────────────────────────

    def _close_all_popovers(self):
        """Close any open popovers/menus."""
        for child in self.observe_children():
            if isinstance(child, Gtk.Popover):
                child.popdown()