# ui/views/feed_tab.py
# Feed tab container - pure view for the Projects notebook's "Feed" sub-tab.
# No business logic, no state mutations.
#
# Public API:
#   class FeedTab(Gtk.Box):
#       get_card_container() -> Gtk.Box
#       append_card(card_widget: Gtk.Widget, card_id: str | None) -> None
#       remove_card(card_id: str) -> None
#       schedule_smart_scroll_to_bottom() -> None
#       show_empty_state() -> None

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from typing import Callable


class FeedTab(Gtk.Box):
    """
    Feed card list for the Projects notebook's "Feed" sub-tab.

    Layout:
      Gtk.Box (vertical)
        └── Gtk.ScrolledWindow
              └── Gtk.Box (vertical, card_container)

    CSS classes:
      .feed-scroll  - the scrolled window
      .feed-card-list - the vertical box holding cards
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_vexpand(True)

        self._card_container: Gtk.Box | None = None
        self._feed_scroll: Gtk.ScrolledWindow | None = None
        self._cards_by_id: dict[str, Gtk.Widget] = {}  # card_id → widget
        self._empty_widget: Gtk.Widget | None = None
        # Phase 5 — Auto-accept toggle callback (set by FeedHandler via set_auto_accept_callback).
        # Stores the caller's function; invoked from _on_auto_accept_toggled when the user clicks
        # the toggle button. None means no callback is wired yet (toggling still updates the
        # visual but does nothing externally). Legacy/Phase-5 compat: FeedHandler's Phase 4
        # code still wires this for the legacy single-toggle path.
        self._auto_accept_callback: Callable[[bool], None] | None = None
        # V2 — Per-type toggle callbacks (set by FeedHandler via set_*_toggle_callback).
        self._diffs_toggle_callback: Callable[[bool], None] | None = None
        self._files_toggle_callback: Callable[[bool], None] | None = None
        self._exec_toggle_callback: Callable[[str], None] | None = None
        # V2 — Agent scope callback (wired by FeedHandler in Phase 6).
        self._agent_scope_callback: Callable[[str], None] | None = None
        # V2 — Exec mode (3-state cycle: off → show → silent → off).
        self._exec_mode: str = "off"
        # Phase 5 — Batch button label (read by tests for assertions; mirrors the actual
        # _batch_accept_button.get_label()).
        self._batch_button_label: str = ""
        # One-shot scroll handler ID for deferred scroll-to-bottom (Bug A fix)
        self._scroll_handler_id: int | None = None
        # Timeout source ID for scroll fallback; disarmed when 'changed' fires (4D-3)
        self._scroll_timeout_id: int | None = None

        # ── Build scrolled card list ────────────────────────────────────
        scroll = Gtk.ScrolledWindow()
        scroll.add_css_class("feed-scroll")
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.AUTOMATIC)
        scroll.set_halign(Gtk.Align.FILL)
        scroll.set_valign(Gtk.Align.FILL)
        self._feed_scroll = scroll

        card_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card_container.add_css_class("feed-card-list")
        card_container.set_spacing(8)
        card_container.set_valign(Gtk.Align.START)
        card_container.set_vexpand(True)
        self._card_container = card_container

        scroll.set_child(card_container)
        self.append(scroll)

        # ── Persistent bottom toolbar (Phase 5 — auto-accept + batch accept) ──────
        # Always visible regardless of pending count. The batch button inside this
        # toolbar is shown only when count >= 2; the auto-accept toggle is always
        # shown. Built eagerly in __init__ so the toggle exists before
        # update_auto_accept_state() is ever called.
        self._toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._toolbar.add_css_class("feed-toolbar")

        # Group 1 — per-type toggles (v2 granular controls; replaces legacy
        # _auto_accept_toggle per SPEC-AUTO-ACCEPT-GRANULAR-1.md §2.3).
        self._diffs_toggle = Gtk.ToggleButton(label="Diffs: OFF")
        self._diffs_toggle.add_css_class("feed-toolbar-toggle")
        self._diffs_toggle.add_css_class("feed-toolbar-toggle-per-type")
        self._diffs_toggle.connect("toggled", self._on_diffs_toggled)

        # Files is a GROUP toggle covering file_created/modified/deleted.
        # Uses Gtk.ToggleButton for consistency with the Diffs toggle. The
        # three underlying prefs are always toggled as a group, so there is
        # no inconsistent-state ambiguity in normal usage.
        self._files_toggle = Gtk.ToggleButton(label="Files: OFF")
        self._files_toggle.add_css_class("feed-toolbar-toggle")
        self._files_toggle.add_css_class("feed-toolbar-toggle-per-type")
        self._files_toggle.connect("toggled", self._on_files_toggled)

        # Exec toggle is a 3-state cycle (off → show → silent → off), NOT a
        # 2-state toggle. GTK has no native 3-state cycle button, so we use
        # a plain Button with a "clicked" handler that computes the next
        # state from the current self._exec_mode.
        self._exec_toggle = Gtk.ToggleButton(label="Exec: OFF")
        self._exec_toggle.add_css_class("feed-toolbar-toggle")
        self._exec_toggle.add_css_class("feed-toolbar-toggle-per-type")
        self._exec_toggle.connect("clicked", self._on_exec_clicked)

        # Separator between toggle group and agent scope.
        self._scope_divider = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self._scope_divider.add_css_class("feed-toolbar-divider")

        # Group 2 — agent scope (placeholder; populated in Phase 6).
        # Gtk.DropDown is used as the widget; the StringList model + callback
        # are wired in Phase 6 when the handler integrates with the agent
        # registry. Phase 5 only constructs the empty dropdown.
        self._agent_dropdown = Gtk.DropDown()
        self._agent_dropdown.add_css_class("feed-toolbar-agent-dropdown")

        # Separator between scope and snooze.
        self._snooze_divider = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self._snooze_divider.add_css_class("feed-toolbar-divider")

        # Group 3 — snooze button. Hidden when count == 0; revealed by
        # update_auto_accept_prefs() when the prefs dict carries snoozed ids.
        self._snooze_button = Gtk.MenuButton(label="Snooze 0")
        self._snooze_button.add_css_class("feed-toolbar-snooze")
        self._snooze_button.set_visible(False)  # hidden until snooze count > 0

        self._divider = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self._divider.add_css_class("feed-toolbar-divider")

        self._batch_accept_button = Gtk.Button(label="Accept All")
        self._batch_accept_button.add_css_class("feed-btn-batch-accept")
        self._batch_accept_button.set_visible(False)  # hidden until count >= 2
        self._batch_accept_button.connect("clicked", self._on_batch_button_clicked)

        self._batch_accept_label = Gtk.Label(label="")
        self._batch_accept_label.add_css_class("feed-batch-bar-info")

        self._toolbar.append(self._auto_accept_toggle)
        self._toolbar.append(self._divider)
        self._toolbar.append(self._batch_accept_button)
        self._toolbar.append(self._batch_accept_label)

        self.append(self._toolbar)

        # When the feed tab becomes visible (mapped), scroll to the bottom so
        # the newest card is shown. This handles the case where GTK4 resets
        # the ScrolledWindow's vadjustment to 0 during page hide/show cycles
        # (Notebook tab switching) — without this, switching to the Feed tab
        # shows the top of the feed even if the user had been at the bottom.
        scroll.connect("map", self._on_scroll_mapped)

    # ── Public API ───────────────────────────────────────────────────────

    def get_card_container(self) -> Gtk.Box:
        """Return the vertical box that holds feed cards."""
        return self._card_container

    def show_empty_state(self) -> None:
        """Clear all cards and show the empty state widget."""
        from ui.views.feed_card import build_empty_feed_widget
        if self._card_container is None:
            return

        # Remove all card widgets, clearing CSS state first (Bug B fix)
        for card_id in list(self._cards_by_id.keys()):
            widget = self._cards_by_id[card_id]
            self._clear_widget_state_recursive(widget)
            if widget in self._card_container:
                self._card_container.remove(widget)
        self._cards_by_id.clear()
        # Show the empty state widget
        empty = build_empty_feed_widget()
        self._card_container.append(empty)
        self._empty_widget = empty

    def append_card(self, card_widget: Gtk.Widget, card_id: str | None = None) -> None:
        """
        Append a card widget to the bottom of the feed (chronological, newest last).
        If card_id is provided, the card can be removed via remove_card().
        Removes the empty state widget if present.
        """
        if self._card_container is None:
            return
        # Remove empty state widget if present
        if self._empty_widget is not None and self._empty_widget in self._card_container:
            self._card_container.remove(self._empty_widget)
            self._empty_widget = None
        # Append to bottom (newest card at bottom - social-media order)
        self._card_container.append(card_widget)
        if card_id is not None:
            self._cards_by_id[card_id] = card_widget

    def remove_card(self, card_id: str) -> None:
        """Remove a card widget by card_id.

        Clears CSS state flags (PRELIGHT/ACTIVE/SELECTED) on the card and
        all its children BEFORE unparenting. This prevents GTK4's
        'Broken accounting of active state for widget' warning that fires
        when a widget is removed while the cursor is over it or while a
        child button is in :active state (e.g. user mid-click on Accept).
        """
        if card_id not in self._cards_by_id:
            return
        widget = self._cards_by_id[card_id]
        # Clear CSS state on the card and all descendant widgets.
        # The 'Broken accounting' warning is about GtkStyleContext state
        # (PRELIGHT/ACTIVE/SELECTED), not focus. unset_state_flags is the
        # documented GTK4 API and is safe to call on widgets that never
        # had the flags set.
        self._clear_widget_state_recursive(widget)
        if self._card_container and widget in self._card_container:
            self._card_container.remove(widget)
        del self._cards_by_id[card_id]      

    def prepend_card(self, card_widget: Gtk.Widget, card_id: str | None = None) -> None:
        """
        Prepend a card widget at the top of the feed (above all other cards).

        Used by lazy-load to insert older cards above the existing feed.
        If card_id is provided, the card can be removed via remove_card().
        """
        if self._card_container is None:
            return
        # Remove empty state widget if present
        if self._empty_widget is not None and self._empty_widget in self._card_container:
            self._card_container.remove(self._empty_widget)
            self._empty_widget = None
        # insert_child_after(child, None) prepends in GTK4
        self._card_container.insert_child_after(card_widget, None)
        if card_id is not None:
            self._cards_by_id[card_id] = card_widget

    def replace_card(self, card_id: str, new_widget: Gtk.Widget) -> None:
        """
        Replace an existing card widget with a new one at the same position.

        Used by FeedHandler.update_card() when a tool call card is updated
        with results - the widget is rebuilt and swapped in-place.
        """
        if card_id not in self._cards_by_id:
            return
        old_widget = self._cards_by_id[card_id]
        if self._card_container is None:
            return
        if old_widget not in self._card_container:
            return

        # Find the position of old_widget, then insert new_widget at the same spot
        children = list(self._card_container)
        try:
            idx = children.index(old_widget)
        except ValueError:
            return

        # Remove old widget - now children[0..idx-1] are what come before new_widget
        self._card_container.remove(old_widget)

        # predecessor is children[idx-1] if idx > 0, else None (insert at start)
        predecessor = children[idx - 1] if idx > 0 else None
        self._card_container.insert_child_after(new_widget, predecessor)
        self._cards_by_id[card_id] = new_widget

    def _clear_widget_state_recursive(self, widget: Gtk.Widget) -> None:
        """
        Recursively clear PRELIGHT/ACTIVE/SELECTED state flags on a widget
        and all its children. Called before removing widgets from the
        container to prevent GTK4's 'Broken accounting of active state'
        warning.
        """
        try:
            widget.unset_state_flags(
                Gtk.StateFlags.PRELIGHT | Gtk.StateFlags.ACTIVE | Gtk.StateFlags.SELECTED
            )
        except Exception:
            pass  # unset_state_flags is safe but we guard anyway
        child = widget.get_first_child()
        while child is not None:
            self._clear_widget_state_recursive(child)
            child = child.get_next_sibling()

    def schedule_scroll_to_bottom(self) -> None:
        """
        Schedule a one-shot scroll-to-bottom that fires AFTER GTK updates
        the vadjustment upper following a layout pass.

        GTK4 does NOT recompute vadjustment.upper synchronously after
        append_child — the upper reflects allocated content height which
        happens during the next frame clock tick. Reading upper immediately
        after appends returns a stale value and can cause the feed to snap
        to the top.

        We connect to the vadjustment's 'changed' signal (fired when
        upper/lower/page-size change) and scroll once, then disconnect.
        If 'changed' has already fired by the time we connect (unlikely
        but safe), we also install a short timeout fallback.
        """
        if self._feed_scroll is None:
            return
        vadj = self._feed_scroll.get_vadjustment()
        if vadj is None:
            return

        # Disconnect any prior one-shot handler to avoid double-firing
        if self._scroll_handler_id is not None:
            try:
                vadj.disconnect(self._scroll_handler_id)
            except Exception:
                pass
            self._scroll_handler_id = None

        # Cancel any prior timeout (defensive — re-entrancy guard)
        if self._scroll_timeout_id is not None:
            try:
                from gi.repository import GLib as _GLib
                _GLib.source_remove(self._scroll_timeout_id)
            except Exception:
                pass
            self._scroll_timeout_id = None

        from gi.repository import GLib

        def _on_adj_changed(adj):
            # Vadjustment upper has been updated — scroll to bottom now
            adj.set_value(adj.get_upper())
            # Disarm the timeout — success path wins (4D-3 fix)
            if self._scroll_timeout_id is not None:
                try:
                    GLib.source_remove(self._scroll_timeout_id)
                except Exception:
                    pass
                self._scroll_timeout_id = None
            # Disconnect this one-shot handler
            if self._scroll_handler_id is not None:
                try:
                    adj.disconnect(self._scroll_handler_id)
                except Exception:
                    pass
                self._scroll_handler_id = None
            return False  # not used for GObject signals

        self._scroll_handler_id = vadj.connect("changed", _on_adj_changed)

        # Safety net: if 'changed' doesn't fire within 150ms (e.g. zero
        # cards added so no layout change), scroll directly and clean up.
        def _timeout_fallback():
            # If we got here, 'changed' didn't fire in time. Scroll now.
            if self._scroll_handler_id is not None:
                vadj.set_value(vadj.get_upper())
                try:
                    vadj.disconnect(self._scroll_handler_id)
                except Exception:
                    pass
                self._scroll_handler_id = None
            self._scroll_timeout_id = None
            return GLib.SOURCE_REMOVE
        self._scroll_timeout_id = GLib.timeout_add(150, _timeout_fallback)

    def schedule_smart_scroll_to_bottom(self) -> None:
        """
        Deferred smart scroll: only scroll to bottom if the user is already
        near the bottom (within 80px), BUT wait for the vadjustment 'changed'
        signal before scrolling so we read the post-layout upper.

        The proximity check uses the pre-append (stale) upper, which is fine:
        we're measuring 'where is the user right now?' not 'where will the
        new bottom be after layout?'. If the user was near the bottom before
        the card was added, they want to see the new card.
        """
        if self._feed_scroll is None:
            return
        vadj = self._feed_scroll.get_vadjustment()
        if vadj is None:
            return
        current = vadj.get_value()
        upper = vadj.get_upper()
        page_size = vadj.get_page_size()
        distance_from_bottom = upper - page_size - current
        if distance_from_bottom >= 80:
            # User has scrolled up to read old cards — don't auto-scroll.
            return
        # User is near the bottom — defer the actual scroll until layout settles.
        self.schedule_scroll_to_bottom()

    def _on_scroll_mapped(self, scroll_window):
        """
        Handler for the ScrolledWindow's 'map' signal — fires when the widget
        becomes visible. Used to scroll to the bottom whenever the Feed tab
        is shown, including after a notebook tab switch.

        Why this exists: GTK4 may reset the ScrolledWindow's vadjustment to 0
        when the widget goes hidden→visible (e.g. switching tabs in the
        parent Notebook). Without this handler, the user lands at the top
        of the feed even though they were just at the bottom.

        Implementation: schedule_scroll_to_bottom() defers the actual scroll
        via the vadjustment 'changed' signal so we read the post-layout
        upper. Returning False from a 'map' handler is a no-op — the signal
        handler return value is ignored.
        """
        self.schedule_scroll_to_bottom()
        return False

    def update_batch_bar(self, pending_count: int) -> None:
        """
        Update the batch accept button inside the persistent bottom toolbar.
        pending_count is the number of consecutive pending file-change cards
        stacked at the bottom of the feed. Button is hidden when count < 2,
        shown with label "Accept All (N)" when count >= 2. (Phase 5)
        """
        if pending_count >= 2:
            self._batch_accept_button.set_label(f"Accept All ({pending_count})")
            self._batch_accept_button.set_visible(True)
        else:
            self._batch_accept_button.set_label("Accept All")
            self._batch_accept_button.set_visible(False)
        self._batch_button_label = self._batch_accept_button.get_label()
        self._batch_accept_label.set_text("")

    # ── Phase 5: Auto-accept toggle API ───────────────────────────────────────

    def set_auto_accept_callback(self, callback: Callable[[bool], None] | None) -> None:
        """
        Install the callback invoked when the user clicks the auto-accept toggle.
        The callback receives the new active state (True = ON, False = OFF).
        Pass None to clear. Called by FeedHandler after set_feed_tab(). (Phase 5)
        """
        self._auto_accept_callback = callback

    def update_auto_accept_state(self, active: bool) -> None:
        """
        Programmatically set the toggle visual state. set_active() does NOT
        fire the 'toggled' signal (verified GTK4 behavior), so this is safe
        to call from the main thread without triggering the user's callback.
        Also updates the label to reflect the new state. (Phase 5)
        """
        self._auto_accept_toggle.set_active(active)
        self._auto_accept_toggle.set_label("Auto-Accept: ON" if active else "Auto-Accept: OFF")

    def _on_auto_accept_toggled(self, button: Gtk.ToggleButton) -> None:
        """
        Handler for the toggle's 'toggled' signal. Fires when the user clicks
        the toggle (programmatic set_active() does NOT emit 'toggled').
        Forwards the new state to the callback installed via
        set_auto_accept_callback(), if any. (Phase 5)
        """
        if self._auto_accept_callback is not None:
            self._auto_accept_callback(button.get_active())

    def _on_batch_button_clicked(self, button: Gtk.Button) -> None:
        """
        Handler for the toolbar batch button's 'clicked' signal. Fires when the
        user clicks the batch accept button. Forwards to the callback installed
        via set_batch_accept_callback(), if any. (Phase 5)
        """
        if self._batch_accept_callback is not None:
            self._batch_accept_callback()

    def _on_batch_accept_clicked(self) -> None:
        """
        Placeholder - overridden by FeedHandler when it wires the batch accept flow.
        The handler calls set_batch_accept_callback() to install the real handler. (Phase 5)
        """
        pass

    def set_batch_accept_callback(self, callback: Callable[[], None]) -> None:
        """
        Install the real batch accept callback. Called by FeedHandler after construction. (Phase 5)

        Stores the callback both on self._batch_accept_callback (used by the new
        _on_batch_button_clicked toolbar handler) AND on self._on_batch_accept_clicked
        (legacy placeholder; kept for backward compatibility with any external code
        that still references the old attribute).
        """
        self._batch_accept_callback = callback
        self._on_batch_accept_clicked = callback
