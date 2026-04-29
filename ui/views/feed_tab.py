# ui/views/feed_tab.py
# Feed tab container — bottom tab bar for project content area (Phase 1).
# Pure view — no business logic, no state mutations.
#
# Public API:
#   class FeedTab(Gtk.Box):
#       get_card_container() -> Gtk.Box
#       get_stack() -> Gtk.Stack
#       show_feed_tab() -> None
#       show_files_tab() -> None
#       show_empty_state() -> None
#       prepend_card(card_widget: Gtk.Widget) -> None
#       remove_card(card_id: str) -> None
#       scroll_to_bottom() -> None

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk


class FeedTab(Gtk.Box):
    """
    Bottom tab container for project content area.

    Layout:
      Gtk.Box (vertical)
        ├── Gtk.StackSwitcher (tab bar: "Files" | "Feed")
        └── Gtk.Stack
             ├── "files" → file_tree (injected)
             └── "feed"  → Gtk.ScrolledWindow → card_container (vertical box)

    CSS classes:
      .feed-tab-bar — the tab switcher row
      .feed-scroll  — the scrolled window for card list
      .feed-card-list — the vertical box holding cards
    """

    def __init__(self, file_tree: Gtk.Widget):
        """
        Args:
            file_tree: existing FileTree widget to show under the "Files" tab.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_vexpand(True)

        self._card_container: Gtk.Box | None = None  # set in _build_feed_tab
        self._feed_scroll: Gtk.ScrolledWindow | None = None
        self._stack: Gtk.Stack | None = None
        self._cards_by_id: dict[str, Gtk.Widget] = {}  # card_id → widget

        # ── Build stack (Files | Feed) ─────────────────────────────────
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_halign(Gtk.Align.FILL)

        # "files" page — inject the existing FileTree
        files_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        files_page.append(file_tree)
        self._stack.add_titled(files_page, "files", "Files")

        # "feed" page — scrollable card list
        feed_page, card_container, scroll = self._build_feed_tab()
        self._card_container = card_container
        self._feed_scroll = scroll
        self._stack.add_titled(feed_page, "feed", "Project Feed")

        # ── Stack switcher (tab bar) ─────────────────────────────────────
        tab_bar = Gtk.StackSwitcher()
        tab_bar.set_stack(self._stack)
        tab_bar.add_css_class("feed-tab-bar")

        self.append(tab_bar)
        self.append(self._stack)

    # ── Private builders ─────────────────────────────────────────────────

    def _build_feed_tab(self) -> tuple[Gtk.Box, Gtk.Box, Gtk.ScrolledWindow]:
        """Build the feed page (scrolled card list). Returns (page, card_container, scroll)."""
        scroll = Gtk.ScrolledWindow()
        scroll.add_css_class("feed-scroll")
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_halign(Gtk.Align.FILL)
        scroll.set_valign(Gtk.Align.FILL)

        card_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card_container.add_css_class("feed-card-list")
        card_container.set_spacing(8)
        card_container.set_valign(Gtk.Align.START)
        card_container.set_vexpand(True)

        scroll.set_child(card_container)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.append(scroll)

        return page, card_container, scroll

    # ── Public API ───────────────────────────────────────────────────────

    def get_card_container(self) -> Gtk.Box:
        """Return the vertical box that holds feed cards. Cards are prepended here."""
        return self._card_container

    def get_stack(self) -> Gtk.Stack:
        """Return the stack for external tab switching."""
        return self._stack

    def show_feed_tab(self) -> None:
        """Switch to the Project Feed tab."""
        self._stack.set_visible_child_name("feed")

    def show_files_tab(self) -> None:
        """Switch to the Files tab."""
        self._stack.set_visible_child_name("files")

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

    def prepend_card(self, card_widget: Gtk.Widget, card_id: str | None = None) -> None:
        """
        Prepend a card widget to the top of the feed (reverse-chronological).
        If card_id is provided, the card can be removed via remove_card().
        Removes the empty state widget if present.
        """
        if self._card_container is None:
            return
        # Remove empty state widget if present
        empty = getattr(self, '_empty_widget', None)
        if empty is not None and empty in self._card_container:
            self._card_container.remove(empty)
            self._empty_widget = None
        # Insert at top (newest card at bottom, so prepend puts newest at top)
        self._card_container.insert_child_at_start(card_widget)
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
        # Scroll to maximum value (bottom of scroll range)
        vadj.set_value(vadj.get_upper())