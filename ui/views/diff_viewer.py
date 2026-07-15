# ui/views/diff_viewer.py
# Diff viewer widget for the main content area.
# Pure view — no git calls, no state. All actions go through callbacks.

import threading
import os
from typing import Callable, Optional

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

from utils.diff_parser import parse_diff, FileDiff
from utils.git_ops import (
    diff_file_against_working_tree,
    diff_working_tree,
    diff_file_against,
    file_log,
)
from utils.escaping import escape_for_pango
from ui.views.diff_card import render_diff_hunks, get_lang_from_path


class DiffViewer(Gtk.Box):
    """
    Diff viewer widget for the main content area.

    Shows current diff for a file, with a toggle to view edit history.
    Historical entries show their diff and a revert button.

    All git calls are dispatched on background threads. UI updates via GLib.idle_add.
    Background results are guarded by _current_request_id (race safety) and
    _disposed (destroy safety).

    Widget hierarchy:
        DiffViewer (Gtk.Box, vertical)
        ├── _header (Gtk.Box, horizontal)
        │   ├── back_btn (Gtk.Button)
        │   ├── _title_label (Gtk.Label)
        │   ├── _subtitle_label (Gtk.Label)
        │   └── _tab_box (Gtk.Box)
        │       ├── _diff_toggle (Gtk.CheckButton)  # group leader
        │       └── _history_toggle (Gtk.CheckButton)  # joins group
        ├── _stack (Gtk.Stack)
        │   ├── "diff" → _diff_scroll (Gtk.ScrolledWindow)
        │   │   └── _diff_box (Gtk.Box, vertical)
        │   └── "history" → _history_scroll (Gtk.ScrolledWindow)
        │       └── _history_list (Gtk.ListBox)
        └── _action_bar (Gtk.Box, horizontal)
            └── _revert_btn (Gtk.Button)

    Args:
        file_path: Relative path to the file (relative to project root).
        project_path: Absolute path to the project root.
        checkpoint_sha: Review checkpoint SHA, or None if no active review.
        on_back: Callable called when the Back button is clicked.
        on_revert: Callable[[str, str, Callable[[], None] | None], None] —
                   (file_path, target_sha, on_complete). The on_complete callback
                   should be invoked by the revert handler when the revert is done,
                   so the viewer can reload the current diff.
    """

    def __init__(
        self,
        file_path: str,
        project_path: str,
        checkpoint_sha: str | None = None,
        on_back: Callable[[], None] | None = None,
        on_revert: Callable[[str, str, Callable[[], None] | None], None] | None = None,
    ):
        # BUG #6: Strengthen input validation — check type and strip whitespace
        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("file_path is required")
        if not isinstance(project_path, str) or not project_path.strip():
            raise ValueError("project_path is required")

        # H12 fix: call super().__init__() before any widget operations
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # State
        self._file_path = file_path
        self._project_path = project_path
        self._checkpoint_sha = checkpoint_sha
        self._on_back = on_back
        self._on_revert = on_revert
        self._selected_sha: str | None = None
        self._history_loaded = False

        # H3 fix: disposal flag
        self._disposed = False
        # H4 fix: request sequence ID
        self._current_request_id = 0

        # CSS: classes defined in ui/styles.py, registered globally by apply_styles()
        self.add_css_class("diff-viewer")

        self._build_ui()
        self._load_current_diff()

    def _build_ui(self):
        """Build the widget hierarchy as shown in class docstring."""
        # Header
        self._header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._header.add_css_class("diff-viewer-header")
        self.append(self._header)

        # Back button
        self._back_btn = Gtk.Button(label="← Back")
        self._back_btn.connect("clicked", self._on_back_clicked)
        self._header.append(self._back_btn)

        # Title (file path) — BUG #2: use set_text() to prevent Pango injection
        self._title_label = Gtk.Label()
        self._title_label.set_text(escape_for_pango(self._file_path))
        self._title_label.set_halign(Gtk.Align.START)
        self._title_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self._title_label.set_hexpand(True)
        self._title_label.add_css_class("diff-viewer-title")
        self._header.append(self._title_label)

        # Subtitle (diff context)
        self._subtitle_label = Gtk.Label(label="")
        self._subtitle_label.set_halign(Gtk.Align.START)
        self._subtitle_label.add_css_class("diff-viewer-subtitle")
        self._header.append(self._subtitle_label)

        # Tab toggles (Diff / History) — CheckButton with group
        self._tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._diff_toggle = Gtk.CheckButton(label="Diff")
        self._diff_toggle.set_active(True)
        self._history_toggle = Gtk.CheckButton(label="History")
        self._history_toggle.set_group(self._diff_toggle)
        self._history_toggle.connect("toggled", self._on_history_toggled)
        self._tab_box.append(self._diff_toggle)
        self._tab_box.append(self._history_toggle)
        self._header.append(self._tab_box)

        # Stack for diff / history views
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        self.append(self._stack)

        # Diff page
        self._diff_scroll = Gtk.ScrolledWindow()
        self._diff_scroll.set_hexpand(True)
        self._diff_scroll.set_vexpand(True)
        self._diff_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._diff_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._diff_scroll.set_child(self._diff_box)
        self._stack.add_named(self._diff_scroll, "diff")

        # History page
        self._history_scroll = Gtk.ScrolledWindow()
        self._history_scroll.set_hexpand(True)
        self._history_scroll.set_vexpand(True)
        self._history_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._history_list = Gtk.ListBox()
        self._history_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._history_scroll.set_child(self._history_list)
        self._stack.add_named(self._history_scroll, "history")

        # BUG #4: Connect row-activated once in _build_ui (not per load)
        self._history_list.connect("row-activated", self._on_history_row_activated)

        # Action bar (revert button)
        self._action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._action_bar.add_css_class("diff-viewer-action-bar")
        self._revert_btn = Gtk.Button(label="Revert file to this version")
        self._revert_btn.add_css_class("diff-viewer-revert-btn")
        self._revert_btn.set_visible(False)  # only shown on historical entries
        self._revert_btn.connect("clicked", self._on_revert_clicked)
        self._action_bar.append(self._revert_btn)
        self.append(self._action_bar)

    # === Async load methods with race guards ===

    def _load_current_diff(self):
        """Load current diff on background thread."""
        self._show_loading()
        self._current_request_id += 1
        req_id = self._current_request_id

        def _do():
            if self._checkpoint_sha:
                result = diff_file_against_working_tree(
                    self._project_path, self._checkpoint_sha, self._file_path
                )
                subtitle = f"since checkpoint {self._checkpoint_sha[:7]}"
            else:
                result = diff_working_tree(self._project_path, self._file_path)
                subtitle = "since HEAD"

            GLib.idle_add(lambda: self._on_diff_loaded(result, subtitle, req_id))

        threading.Thread(target=_do, daemon=True).start()

    def _on_diff_loaded(self, result, subtitle: str, req_id: int):
        """Handle diff load result. Ignores stale results."""
        if self._disposed:
            return
        if req_id != self._current_request_id:
            return

        self._subtitle_label.set_text(subtitle)

        if not result.success:
            self._show_error(result.error)
            return

        if not result.stdout.strip():
            self._show_placeholder("No changes to this file.")
            return

        parsed = parse_diff(result.stdout)
        if not parsed.files:
            self._show_placeholder("No changes to this file.")
            return

        file_diff = parsed.files[0]

        # H8 fix: binary file handling — caller checks before calling render_diff_hunks
        if file_diff.is_binary:
            self._show_placeholder("Binary file — not shown")
            return

        # Clear previous content
        while self._diff_box.get_first_child() is not None:
            self._diff_box.remove(self._diff_box.get_first_child())

        lang = get_lang_from_path(file_diff.display_path)
        self._diff_box.append(render_diff_hunks(file_diff.hunks, lang))
        self._stack.set_visible_child_name("diff")

        # Current diff view never shows revert
        self._revert_btn.set_visible(False)

    def _load_historical_diff(self, sha: str):
        """Load diff from a historical commit on background thread."""
        self._show_loading()
        self._current_request_id += 1
        req_id = self._current_request_id

        def _do():
            result = diff_file_against(self._project_path, sha, self._file_path)
            subtitle = f"Diff from {sha[:7]} → HEAD"
            GLib.idle_add(lambda: self._on_historical_diff_loaded(result, subtitle, sha, req_id))

        threading.Thread(target=_do, daemon=True).start()

    def _on_historical_diff_loaded(self, result, subtitle: str, sha: str, req_id: int):
        if self._disposed:
            return
        if req_id != self._current_request_id:
            return

        self._subtitle_label.set_text(subtitle)

        if not result.success:
            self._show_error(result.error)
            return

        if not result.stdout.strip():
            self._show_placeholder("No changes since this commit.")
            self._revert_btn.set_visible(True)
            return

        parsed = parse_diff(result.stdout)
        if not parsed.files:
            self._show_placeholder("No changes since this commit.")
        else:
            file_diff = parsed.files[0]
            if file_diff.is_binary:
                self._show_placeholder("Binary file — not shown")
            else:
                while self._diff_box.get_first_child() is not None:
                    self._diff_box.remove(self._diff_box.get_first_child())
                lang = get_lang_from_path(file_diff.display_path)
                self._diff_box.append(render_diff_hunks(file_diff.hunks, lang))

        self._stack.set_visible_child_name("diff")
        self._revert_btn.set_visible(True)

    def _load_history(self):
        """Load file commit history on background thread."""
        if self._history_loaded:
            return
        self._history_loaded = True
        self._current_request_id += 1
        req_id = self._current_request_id

        def _do():
            result = file_log(self._project_path, self._file_path, count=20)
            entries = []
            if result.success and result.stdout.strip():
                for line in result.stdout.strip().splitlines():
                    parts = line.split("\x1f")
                    if len(parts) == 3:
                        entries.append({"sha": parts[0], "date": parts[1], "message": parts[2]})
            GLib.idle_add(lambda: self._on_history_loaded(entries, req_id))

        threading.Thread(target=_do, daemon=True).start()

    def _on_history_loaded(self, entries: list[dict], req_id: int):
        if self._disposed:
            return
        if req_id != self._current_request_id:
            return

        # Clear previous rows
        while self._history_list.get_first_child() is not None:
            self._history_list.remove(self._history_list.get_first_child())

        # BUG #3: Wrap placeholder in Gtk.ListBoxRow before appending to ListBox
        if not entries:
            row = Gtk.ListBoxRow()
            placeholder = Gtk.Label(label="No commit history for this file.")
            placeholder.set_halign(Gtk.Align.CENTER)
            placeholder.set_valign(Gtk.Align.CENTER)
            placeholder.add_css_class("diff-viewer-subtitle")
            row.set_child(placeholder)
            self._history_list.append(row)
            return

        for entry in entries:
            row = Gtk.ListBoxRow()
            row.sha = entry["sha"]
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row_box.add_css_class("diff-history-row")

            sha_lbl = Gtk.Label(label=entry["sha"][:7])
            sha_lbl.add_css_class("diff-history-row-sha")

            date_lbl = Gtk.Label(label=entry["date"][:10])
            date_lbl.add_css_class("diff-history-row-date")

            # BUG #2: escape commit message to prevent Pango injection
            msg_lbl = Gtk.Label()
            msg_lbl.set_text(escape_for_pango(entry["message"]))
            msg_lbl.add_css_class("diff-history-row-msg")
            msg_lbl.set_ellipsize(3)
            msg_lbl.set_hexpand(True)

            row_box.append(sha_lbl)
            row_box.append(date_lbl)
            row_box.append(msg_lbl)
            row.set_child(row_box)
            self._history_list.append(row)

        # BUG #4: row-activated signal is already connected in _build_ui (one-time init)

    # === UI callbacks ===

    def _on_back_clicked(self, button):
        if self._on_back:
            self._on_back()

    def _on_history_toggled(self, button):
        if button.get_active():
            self._stack.set_visible_child_name("history")
            self._load_history()

    def _on_history_row_activated(self, listbox, row):
        # BUG #3: guard against rows without sha (placeholder rows, etc.)
        if not hasattr(row, 'sha'):
            return
        self._selected_sha = row.sha
        self._load_historical_diff(row.sha)

    def _on_revert_clicked(self, button):
        if self._selected_sha is None or self._on_revert is None:
            return

        short_sha = self._selected_sha[:7]
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Revert {self._file_path}?",
            secondary_text=(
                f"This will restore the file to its state from commit {short_sha}. "
                f"Any uncommitted changes to this file will be lost."
            ),
        )
        dialog.connect("response", self._on_revert_confirmed)
        dialog.present()

    def _on_revert_confirmed(self, dialog, response_id):
        dialog.destroy()
        if response_id != Gtk.ResponseType.YES:
            return

        target_sha = self._selected_sha
        self._selected_sha = None
        self._revert_btn.set_visible(False)

        # BUG #5: Replace time.sleep(1.0) with callback-based revert completion.
        # The on_revert callback receives an on_complete parameter that is
        # invoked when the revert is done.
        self._show_placeholder(f"Reverting to {target_sha[:7]}...")

        def _on_revert_complete():
            if not self._disposed:
                self._load_current_diff()

        # Dispatch the actual revert with completion callback
        self._on_revert(self._file_path, target_sha, _on_revert_complete)

    # === Helpers ===

    def _show_loading(self):
        if self._disposed:
            return
        while self._diff_box.get_first_child() is not None:
            self._diff_box.remove(self._diff_box.get_first_child())
        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_margin_top(24)
        spinner.set_margin_bottom(24)
        spinner.set_halign(Gtk.Align.CENTER)
        self._diff_box.append(spinner)
        self._stack.set_visible_child_name("diff")

    def _show_placeholder(self, text: str):
        if self._disposed:
            return
        while self._diff_box.get_first_child() is not None:
            self._diff_box.remove(self._diff_box.get_first_child())
        lbl = Gtk.Label(label=text)
        lbl.add_css_class("diff-viewer-subtitle")
        lbl.set_margin_top(24)
        lbl.set_margin_bottom(24)
        lbl.set_halign(Gtk.Align.CENTER)
        self._diff_box.append(lbl)
        self._stack.set_visible_child_name("diff")

    def _show_error(self, error: str):
        self._show_placeholder(f"Error: {error}")

    # H3/M16/M21/M25 fix: GTK4 dispose vfunc
    # BUG #1: call super().do_dispose() at end
    def do_dispose(self):
        self._disposed = True
        super().do_dispose()