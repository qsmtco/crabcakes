# ui/views/review_bar.py
# Review bar widget — overlay at top of project tab chat area.
# Contains review mode dropdown, status label, and action buttons.
# Pure view — no git calls, no state. All actions go through callbacks.

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


class ReviewBar(Gtk.Box):
    """
    Review bar widget for project tab.

    Layout:
    ┌──────────────────────────────────────────────────────────────────┐
    │  [Review ▾]  │  🔍 No active session  │  [Start Review]         │
    └──────────────────────────────────────────────────────────────────┘

    Signals: None (all interaction via constructor callbacks).

    Args:
        on_mode_changed: Callable[[str], None] — "off" | "review"
        on_start_clicked: Callable[[], None]
        on_check_clicked: Callable[[], None]
    """

    def __init__(
        self,
        *,
        on_mode_changed,
        on_start_clicked,
        on_check_clicked,
    ):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("review-bar")
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.set_valign(Gtk.Align.CENTER)

        self._on_mode_changed = on_mode_changed
        self._on_start_clicked = on_start_clicked
        self._on_check_clicked = on_check_clicked

        # Mode dropdown
        self._mode_dropdown = Gtk.DropDown()
        mode_model = Gtk.StringList()
        mode_model.append("off")
        mode_model.append("review")
        self._mode_dropdown.set_model(mode_model)
        self._mode_dropdown.set_selected(0)  # default: "off"
        self._mode_dropdown.connect("notify::selected-item", self._on_mode_dropdown_changed)

        # Status label
        self._status_label = Gtk.Label(label="No active session")
        self._status_label.add_css_class("review-bar-status")
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_hexpand(True)

        # Buttons container
        self._buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._buttons_box.set_halign(Gtk.Align.END)

        # Start Review button
        self._btn_start = Gtk.Button(label="Start Review")
        self._btn_start.add_css_class("review-bar-btn-start")
        self._btn_start.connect("clicked", lambda _: self._on_start_clicked())

        # Check Changes button
        self._btn_check = Gtk.Button(label="Check Changes")
        self._btn_check.add_css_class("review-bar-btn-check")
        self._btn_check.connect("clicked", lambda _: self._on_check_clicked())
        self._btn_check.set_visible(False)

        # Accept All button
        self._btn_accept = Gtk.Button(label="Accept All")
        self._btn_accept.add_css_class("review-bar-btn-accept")
        self._btn_accept.set_visible(False)

        # Reject All button
        self._btn_reject = Gtk.Button(label="Reject All")
        self._btn_reject.add_css_class("review-bar-btn-reject")
        self._btn_reject.set_visible(False)

        self._buttons_box.append(self._btn_start)
        self._buttons_box.append(self._btn_check)
        self._buttons_box.append(self._btn_accept)
        self._buttons_box.append(self._btn_reject)

        self.append(self._mode_dropdown)
        self.append(self._status_label)
        self.append(self._buttons_box)

        # Callbacks for accept/reject set externally via set_accept_callback
        self._on_accept_all = None
        self._on_reject_all = None
        self._btn_accept.connect("clicked", lambda _: self._on_accept_all() if self._on_accept_all else None)
        self._btn_reject.connect("clicked", lambda _: self._on_reject_all() if self._on_reject_all else None)

    def set_accept_callback(self, cb):
        """Set the Accept All callback."""
        self._on_accept_all = cb

    def set_reject_callback(self, cb):
        """Set the Reject All callback."""
        self._on_reject_all = cb

    def _on_mode_dropdown_changed(self, dropdown, _pspec):
        """Handle mode dropdown change."""
        model = dropdown.get_model()
        selected = dropdown.get_selected()
        if selected != Gtk.INVALID_LIST_POSITION:
            mode = model.get_item(selected)
            self._on_mode_changed(mode)

    # ── View updates ────────────────────────────────────────────────────

    def set_review_mode(self, mode: str) -> None:
        """Update dropdown without firing callback."""
        model = self._mode_dropdown.get_model()
        for i in range(model.get_n_items()):
            if model.get_item(i) == mode:
                self._mode_dropdown.set_selected(i)
                break

    def set_status(self, text: str) -> None:
        """Update status label."""
        self._status_label.set_text(text)

    def set_state_idle(self) -> None:
        """No active session. Show: mode dropdown + 'Start Review' button."""
        self._status_label.set_text("No active session")
        self._btn_start.set_visible(True)
        self._btn_check.set_visible(False)
        self._btn_accept.set_visible(False)
        self._btn_reject.set_visible(False)

    def set_state_reviewing(self, checkpoint_sha: str) -> None:
        """Active review session. Show: status + 'Check Changes' button."""
        short_sha = checkpoint_sha[:7] if checkpoint_sha else "unknown"
        self._status_label.set_text(f"Reviewing checkpoint {short_sha}")
        self._btn_start.set_visible(False)
        self._btn_check.set_visible(True)
        self._btn_accept.set_visible(False)
        self._btn_reject.set_visible(False)

    def set_state_has_changes(self, file_count: int, additions: int, deletions: int) -> None:
        """Changes detected. Show: stats + 'Check' + 'Accept All' + 'Reject All'."""
        self._status_label.set_text(
            f"{file_count} file{'s' if file_count != 1 else ''} changed (+{additions}/-{deletions})"
        )
        self._btn_start.set_visible(False)
        self._btn_check.set_visible(True)
        self._btn_accept.set_visible(True)
        self._btn_reject.set_visible(True)

    def set_loading(self, loading: bool) -> None:
        """Show/hide loading state — disable buttons during git operations."""
        for btn in [self._btn_start, self._btn_check, self._btn_accept, self._btn_reject]:
            btn.set_sensitive(not loading)
        if loading:
            self.add_css_class("review-bar-loading")
        else:
            self.remove_css_class("review-bar-loading")
