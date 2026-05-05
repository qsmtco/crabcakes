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

        # ── Build scrolled card list ────────────────────────────────────
        scroll = Gtk.ScrolledWindow()
        scroll.add_css_class("feed-scroll")
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
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
        Called after loading persisted cards on project open.
        """
        if self._feed_scroll is None:
            return
        vadj = self._feed_scroll.get_vadjustment()
        if vadj is None:
            return
        vadj.set_value(vadj.get_upper())
