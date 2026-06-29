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
        # Batch accept bar (Phase 5): shown when ≥2 consecutive file-change cards are pending
        self._batch_bar: Gtk.Box | None = None
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
        Show or hide the batch accept bar based on pending consecutive file-change cards.
        pending_count is the number of consecutive pending file-change cards stacked
        at the bottom of the feed. Bar is hidden if count < 2. (Phase 5)
        """
        if pending_count < 2:
            if self._batch_bar is not None:
                self._batch_bar.set_visible(False)
            return
        if self._batch_bar is None:
            # Lazy-create on first show
            self._batch_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            self._batch_bar.add_css_class("feed-batch-bar")
            info_label = Gtk.Label()
            info_label.add_css_class("feed-batch-bar-info")
            self._batch_bar.append(info_label)
            self._batch_bar._info_label = info_label  # type: ignore[attr-defined]

            accept_btn = Gtk.Button(label="Accept All")
            accept_btn.add_css_class("feed-btn-batch-accept")
            accept_btn.connect("clicked", lambda _: self._on_batch_accept_clicked())
            self._batch_bar.append(accept_btn)
            self._batch_bar._accept_btn = accept_btn  # type: ignore[attr-defined]

            # Insert before feed_scroll in the parent (pinned to top, outside scrolled window)
            parent = self._feed_scroll.get_parent()
            if parent is not None:
                parent.prepend(self._batch_bar)

        # Update the count text
        self._batch_bar._info_label.set_text(  # type: ignore[attr-defined]
            f"{pending_count} file changes pending"
        )
        self._batch_bar.set_visible(True)

    def _on_batch_accept_clicked(self) -> None:
        """
        Placeholder - overridden by FeedHandler when it wires the batch accept flow.
        The handler calls set_batch_accept_callback() to install the real handler. (Phase 5)
        """
        pass

    def set_batch_accept_callback(self, callback: Callable[[], None]) -> None:
        """
        Install the real batch accept callback. Called by FeedHandler after construction. (Phase 5)
        """
        self._on_batch_accept_clicked = callback
