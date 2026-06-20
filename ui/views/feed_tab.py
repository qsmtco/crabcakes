# ui/views/feed_tab.py
# Feed tab container — pure view for the Projects notebook's "Feed" sub-tab.
# No business logic, no state mutations.
#
# Public API:
#   class FeedTab(Gtk.Box):
#       get_card_container() -> Gtk.Box
#       append_card(card_widget: Gtk.Widget, card_id: str | None) -> None
#       remove_card(card_id: str) -> None
#       scroll_to_bottom() -> None
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
      .feed-scroll  — the scrolled window
      .feed-card-list — the vertical box holding cards
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

    # ── Public API ───────────────────────────────────────────────────────

    def get_card_container(self) -> Gtk.Box:
        """Return the vertical box that holds feed cards."""
        return self._card_container

    def show_empty_state(self) -> None:
        """Clear all cards and show the empty state widget."""
        from ui.views.feed_card import build_empty_feed_widget
        if self._card_container is None:
            return

        # Remove all card widgets
        for card_id in list(self._cards_by_id.keys()):
            widget = self._cards_by_id[card_id]
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
        # Append to bottom (newest card at bottom — social-media order)
        self._card_container.append(card_widget)
        if card_id is not None:
            self._cards_by_id[card_id] = card_widget

    def remove_card(self, card_id: str) -> None:
        """Remove a card widget by card_id."""
        if card_id not in self._cards_by_id:
            return
        widget = self._cards_by_id[card_id]
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
        with results — the widget is rebuilt and swapped in-place.
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

        # Remove old widget — now children[0..idx-1] are what come before new_widget
        self._card_container.remove(old_widget)

        # predecessor is children[idx-1] if idx > 0, else None (insert at start)
        predecessor = children[idx - 1] if idx > 0 else None
        self._card_container.insert_child_after(new_widget, predecessor)
        self._cards_by_id[card_id] = new_widget

    def scroll_to_bottom(self) -> None:
        """
        Scroll the feed so the newest card (bottom of list) is visible.
        Called after loading persisted cards on project open (unconditional).
        """
        if self._feed_scroll is None:
            return
        vadj = self._feed_scroll.get_vadjustment()
        if vadj is None:
            return
        vadj.set_value(vadj.get_upper())

    def smart_scroll_to_bottom(self) -> None:
        """
        Only scroll to bottom if the user is already near the bottom (within 80px).
        If the user has scrolled up to read old cards, do NOT auto-scroll —
        preserve their reading position. (Phase 4)

        Distinguishes from scroll_to_bottom() (unconditional) which is used
        on project open where we always want to jump to the newest.
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
        if distance_from_bottom < 80:
            vadj.set_value(upper)

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
        Placeholder — overridden by FeedHandler when it wires the batch accept flow.
        The handler calls set_batch_accept_callback() to install the real handler. (Phase 5)
        """
        pass

    def set_batch_accept_callback(self, callback: Callable[[], None]) -> None:
        """
        Install the real batch accept callback. Called by FeedHandler after construction. (Phase 5)
        """
        self._on_batch_accept_clicked = callback
