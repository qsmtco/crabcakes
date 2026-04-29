# ui/handlers/feed_handler.py
# Feed state management + card lifecycle (Phase 2).
# Delegates rendering to feed_card.py, git ops to git_ops.py.
# All GTK via GLib.idle_add(). All git operations run in background threads.
#
# Architecture: one handler per subsystem. Does NOT import other handlers.
# Window wires cross-handler communication via callbacks set in constructor.
# No GTK calls from background threads — always via GLib.idle_add().

from dataclasses import dataclass
import logging
import threading
import uuid
from datetime import datetime, timezone

from models.feed_card import FeedCardData
from ui.views.feed_card import build_feed_card
from utils import git_ops
from utils import feed_store

_logger = logging.getLogger(__name__)


class FeedHandler:
    """
    Manages project feed state and coordinates card lifecycle.

    Card lifecycle: add_card() → build widget → prepend to FeedTab
    Button actions: handle_review/accept/reject → GLib.idle_add for GTK
    Git operations: run in background threads, callback to main thread on completion

    Args:
        GLib:                    gi.repository.GLib module — for idle_add dispatch
        feed_tab:                FeedTab instance — for card prepend/remove
        on_populate_input:       Callable[[str], None] — fill input box for Review
        on_send_to_agent:        Callable[[str, str], None] — send message to agent
        on_tab_switch:           Callable[[], None] — switch to feed tab
        on_card_added:           Callable[[str], None] | None — card_id after add
    """

    def __init__(
        self,
        *,
        GLib,                        # gi.repository.GLib
        feed_tab,                    # FeedTab instance
        on_populate_input,            # callback(text) — fills input box (Review)
        on_send_to_agent,             # callback(session_key, text) — send to agent
        on_tab_switch,                # callback() — switch to feed tab
        on_card_added=None,           # callback(card_id) | None
    ):
        self._GLib = GLib
        self._feed_tab = feed_tab
        self._on_populate_input = on_populate_input
        self._on_send_to_agent = on_send_to_agent
        self._on_tab_switch = on_tab_switch
        self._on_card_added = on_card_added

        # Card storage: card_id → FeedCardData
        self._cards: dict[str, FeedCardData] = {}
        # Widget storage: card_id → Gtk.Widget
        self._card_widgets: dict[str, Gtk.Widget] = {}
        # Project → [card_ids] index (newest first)
        self._project_cards: dict[str, list[str]] = {}
        # Project name → project path lookup (for persistence)
        self._project_paths: dict[str, str] = {}
        # True when loading persisted cards (skips redundant feed.json writes)
        self._loading = False

    # ─────────────────────────────────────────────────────────────────
    # Card lifecycle
    # ─────────────────────────────────────────────────────────────────

    def add_card(self, card_data: FeedCardData) -> str:
        """
        Add a card to the project feed.

        1. Assign unique card_id (uuid4)
        2. Store in self._cards[card_id]
        3. Index under project_name
        4. Build widget via build_feed_card()
        5. Prepend to feed_tab
        6. Persist to feed.json via feed_store.append_feed_card()
        7. Return card_id

        Thread-safe: GTK operations via GLib.idle_add().
        """
        card_id = str(uuid.uuid4())
        card_data.card_id = card_id

        # Store data
        self._cards[card_id] = card_data

        # Index under project
        proj = card_data.project_name
        if proj not in self._project_cards:
            self._project_cards[proj] = []
        self._project_cards[proj].insert(0, card_id)  # newest first

        # Build widget
        widget = build_feed_card(
            card_data,
            on_review=self._make_review_cb(card_id),
            on_accept=self._make_accept_cb(card_id),
            on_reject=self._make_reject_cb(card_id),
            on_copy=self._make_copy_cb(card_data),
        )

        self._card_widgets[card_id] = widget

        # Get project path from card metadata (set by on_project_opened load path)
        project_path = card_data.metadata.get("project_path", "")

        # Prepend to feed tab on main thread, then persist
        def _prepend():
            self._feed_tab.prepend_card(widget, card_id)
            if self._on_card_added:
                self._on_card_added(card_id)

        def _persist():
            if project_path and hasattr(card_data, 'to_dict') and not self._loading:
                feed_store.append_feed_card(project_path, card_data)

        self._GLib.idle_add(_prepend)
        # Persist in background to avoid blocking UI.
        # Skip persistence when _loading=True (cards already on disk from load).
        if project_path and not self._loading:
            t = threading.Thread(target=_persist, daemon=True)
            t.start()

        return card_id

    def remove_card(self, card_id: str) -> None:
        """Remove a card from the feed."""
        if card_id not in self._cards:
            return

        proj = self._cards[card_id].project_name
        if proj in self._project_cards and card_id in self._project_cards[proj]:
            self._project_cards[proj].remove(card_id)

        del self._cards[card_id]

        widget = self._card_widgets.pop(card_id, None)

        def _remove():
            self._feed_tab.remove_card(card_id)

        self._GLib.idle_add(_remove)

    def get_card(self, card_id: str) -> FeedCardData | None:
        """Get card data by ID."""
        return self._cards.get(card_id)

    def get_cards_for_project(self, project_name: str) -> list[FeedCardData]:
        """Get all cards for a project, newest first."""
        card_ids = self._project_cards.get(project_name, [])
        return [self._cards[cid] for cid in card_ids if cid in self._cards]

    def clear_project(self, project_name: str) -> None:
        """Remove all cards for a project (on project close)."""
        card_ids = self._project_cards.get(project_name, [])
        for cid in list(card_ids):
            widget = self._card_widgets.pop(cid, None)
            del self._cards[cid]
        if project_name in self._project_cards:
            del self._project_cards[project_name]

        def _clear():
            # FeedTab clears itself when switching projects
            pass

        self._GLib.idle_add(_clear)

    # ─────────────────────────────────────────────────────────────────
    # Project lifecycle hooks
    # ─────────────────────────────────────────────────────────────────

    def on_project_opened(self, project_name: str, project_path: str) -> None:
        """
        Called when a project opens.

        1. Load cards from .crabcakes/feed.json via feed_store.load_feed()
        2. Render all cards (chronological order → newest at bottom)
        3. Switch to Project Feed tab (default tab on open)
        4. Auto-scroll to bottom (newest card visible)
        5. If no cards, show empty state widget
        """
        # Store project_path for persistence on new card adds
        self._project_paths[project_name] = project_path

        def _load_and_render():
            # Mark loading mode — add_card skips persistence for already-saved cards
            self._loading = True

            # Load persisted cards from .crabcakes/feed.json
            cards = feed_store.load_feed(project_path)

            if not cards:
                self._GLib.idle_add(lambda: self._feed_tab.show_empty_state())
                self._GLib.idle_add(lambda: self._feed_tab.show_feed_tab())
                self._loading = False
                return

            # Seed state: set metadata, store widgets/data
            for card in cards:
                if not card.metadata:
                    card.metadata = {}
                card.metadata["project_path"] = project_path

            # Index by project (newest first)
            if project_name not in self._project_cards:
                self._project_cards[project_name] = []
            for card in cards:
                if card.card_id:
                    self._project_cards[project_name].append(card.card_id)

            # Build all widgets (pure Python — no GTK yet)
            for card in cards:
                widget = build_feed_card(
                    card,
                    on_review=self._make_review_cb(card.card_id),
                    on_accept=self._make_accept_cb(card.card_id),
                    on_reject=self._make_reject_cb(card.card_id),
                    on_copy=self._make_copy_cb(card),
                )
                self._card_widgets[card.card_id] = widget
                self._cards[card.card_id] = card

            # Switch to feed tab on main thread (default tab on project open)
            self._GLib.idle_add(lambda: self._feed_tab.show_feed_tab())

            # Add each card to the feed on main thread
            def _add_card_widget(card):
                widget = self._card_widgets.get(card.card_id)
                if widget:
                    self._feed_tab.prepend_card(widget, card.card_id)

            for card in reversed(cards):  # oldest at bottom → newest at top
                self._GLib.idle_add(lambda c=card: _add_card_widget(c))

            # Auto-scroll to bottom (newest card visible) on main thread
            self._GLib.idle_add(lambda: self._feed_tab.scroll_to_bottom())

            self._loading = False

        t = threading.Thread(target=_load_and_render, daemon=True)
        t.start()

    def on_project_closed(self, project_name: str) -> None:
        """Called when project closes. Clear cards for this project."""
        self.clear_project(project_name)
        def _clear():
            self._feed_tab.show_empty_state()
        self._GLib.idle_add(_clear)

    # ─────────────────────────────────────────────────────────────────
    # Button action handlers
    # ─────────────────────────────────────────────────────────────────

    def handle_review(self, card_id: str) -> None:
        """Review button clicked — populate input box with review prompt."""
        card = self._cards.get(card_id)
        if card is None:
            return

        # Build review prompt based on card type
        if card.card_type == "git_commit":
            prompt = f"Review commit {card.commit_sha or '?'}: '{card.title}'. Is this change accurate?"
        elif card.card_type == "diff":
            fp = card.file_path or "unknown file"
            delta = ""
            if card.additions is not None or card.deletions is not None:
                delta = f" +{card.additions or 0}/-{card.deletions or 0} lines"
            prompt = f"Review changes to {fp}{delta}. Verify correctness."
        elif card.card_type == "file_created":
            prompt = f"Review new file {card.file_path or '?'}. Is this needed and correctly placed?"
        elif card.card_type == "file_deleted":
            prompt = f"Review deleted file {card.file_path or '?'}. Was this intentional?"
        elif card.card_type == "task":
            prompt = f"Review task: {card.title}. Status: {card.body or 'unknown'}. Is this done?"
        elif card.card_type == "system":
            fp = card.file_path or "?"
            prompt = f"System detected change to {fp}. Verify this change."
        else:
            prompt = f"Review: {card.title}. {card.body}"

        self._on_populate_input(prompt)
        self._on_tab_switch()

    def handle_accept(self, card_id: str) -> None:
        """
        Accept button clicked.

        For git-backed cards (diff, file_created, file_deleted):
          1. Stage + commit in background thread
          2. Mark card.accepted = True on main thread
          3. Visual feedback via CSS class

        For other card types:
          1. Mark card.accepted = True
        """
        card = self._cards.get(card_id)
        if card is None:
            return

        if card.card_type in ("diff", "file_created", "file_deleted"):
            project_path = card.metadata.get("project_path", "")
            if not project_path:
                return

            def _git_accept():
                result_stage = git_ops.stage_all(project_path)
                if not result_stage.success:
                    _logger.warning("handle_accept: git stage failed for %s", project_path)
                    return
                commit_msg = f"Accept: {card.title}"
                result_commit = git_ops.commit(project_path, commit_msg)
                if result_commit.success:
                    card.accepted = True
                    card.metadata["project_path"] = project_path
                    # Persist to feed.json
                    feed_store.update_feed_card(project_path, card_id, {"accepted": True})
                    # Update visual on main thread
                    def _mark():
                        self._update_card_visual(card_id, accepted=True)
                    self._GLib.idle_add(_mark)

            t = threading.Thread(target=_git_accept, daemon=True)
            t.start()
        else:
            card.accepted = True
            self._update_card_visual(card_id, accepted=True)

    def handle_reject(self, card_id: str) -> None:
        """
        Reject button clicked.

        For git-backed cards:
          1. Revert changes in background thread
          2. Mark card.accepted = False
          3. Notify agent via on_send_to_agent

        For other cards:
          1. Mark card.accepted = False
        """
        card = self._cards.get(card_id)
        if card is None:
            return

        if card.card_type in ("diff", "file_created", "file_deleted"):
            project_path = card.metadata.get("project_path", "")
            if not project_path:
                return

            def _git_reject():
                fp = card.file_path
                sha = card.commit_sha or "HEAD"
                if fp:
                    git_ops.checkout_paths(project_path, sha, [fp])

                def _mark():
                    card.accepted = False
                    card.metadata["project_path"] = project_path
                    self._update_card_visual(card_id, accepted=False)
                    # Persist to feed.json
                    feed_store.update_feed_card(project_path, card_id, {"accepted": False})
                    # Notify agent
                    msg = f"[PM] Rejected change: {card.title}"
                    self._on_send_to_agent(f"project:{card.project_name}", msg)
                self._GLib.idle_add(_mark)

            t = threading.Thread(target=_git_reject, daemon=True)
            t.start()
        else:
            card.accepted = False
            self._update_card_visual(card_id, accepted=False)

    def handle_copy(self, text: str) -> None:
        """Copy card body text to clipboard."""
        def _copy():
            import gi
            gi.require_version('Gtk', '4.0')
            from gi.repository import Gdk
            display = Gdk.Display.get_default()
            if display is None:
                return
            clipboard = display.get_clipboard()
            clipboard.set(text)
        self._GLib.idle_add(_copy)

    # ─────────────────────────────────────────────────────────────────
    # CrabWatch integration (Phase 5 stub — no-op now)
    # ─────────────────────────────────────────────────────────────────

    def on_filesystem_event(self, card_data: FeedCardData) -> None:
        """
        Entry point for CrabWatch file change events.
        Same as add_card() but source is always 'system' or 'crabwatch'.
        """
        card_data.source = "system"
        self.add_card(card_data)

    # ─────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────

    def _make_review_cb(self, card_id: str):
        def cb(cid=card_id):
            self.handle_review(cid)
        return cb

    def _make_accept_cb(self, card_id: str):
        def cb(cid=card_id):
            self.handle_accept(cid)
        return cb

    def _make_reject_cb(self, card_id: str):
        def cb(cid=card_id):
            self.handle_reject(cid)
        return cb

    def _make_copy_cb(self, card_data: FeedCardData):
        body = card_data.body or card_data.title
        def cb(text=body):
            self.handle_copy(text)
        return cb

    def _update_card_visual(self, card_id: str, accepted: bool) -> None:
        """Apply accepted/rejected CSS class to card widget."""
        widget = self._card_widgets.get(card_id)
        if widget is None:
            return
        # accepted=True → add feed-card-accepted, remove feed-card-rejected
        # accepted=False → add feed-card-rejected, remove feed-card-accepted
        cls_add = "feed-card-accepted" if accepted else "feed-card-rejected"
        cls_rem = "feed-card-rejected" if accepted else "feed-card-accepted"
        widget.add_css_class(cls_add)
        widget.remove_css_class(cls_rem)

        # Update card data
        card = self._cards.get(card_id)
        if card:
            card.accepted = accepted